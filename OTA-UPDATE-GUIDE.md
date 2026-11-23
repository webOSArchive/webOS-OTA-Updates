# HP TouchPad community OTA — master guide

Start here. This is the index for the OTA project, followed by the **low-level flash
mechanics** that every other document depends on: how a package is staged, how the
update ramdisk is built and booted, and how to recover a device that gets stuck in it.

---

## Document map

| Document | What it covers | Read it when |
|----------|----------------|--------------|
| **This document** | The OTA mechanism itself: building IPKs, session files, `make-update-uimage`, the update ramdisk, recovery | You need to know how the flash actually works, or something failed during one |
| **`OTA-3.1.0.md`** | The September 2026 design for CE OTA: trust model, signing key, what the image bakes | The key or the trust model |
| `webos-update-server/DEPLOY.md` | Deploying and configuring the update server | Standing up or moving the server |
| `otaready-app/CLAUDE.md` | The OTA Ready client: daemon, install flow, on-device lessons | Working on the client |
| `keys/README.md` | The CE OTA signing key, its algorithm and fingerprint | Anything involving payload signing |
| `../webos-doctor-ce/Docs/OTA-HANDOFF.md` | Where CE OTA stands; payloads; the armed-flash runbook | Releasing an update |

The 3.0.5-era documents (`OTA-3.0.5.md`, `Update Baselines.md`) and the OMA DM server were
removed on 2026-11-23: OTAs start at CE 3.1.0. They are in git history.

---

## Where the project stands

CE OTA is in production: OTA Ready 3.x from App Museum II takes a CE 3.1.0 device to
3.2.0 through System Updates' Install Now, with signed manifests and a per-release device
filter. Payloads are rootfs deltas built by `make-payload.py` in `../webos-doctor-ce`.
Current state and next steps: that project's `Docs/OTA-HANDOFF.md`.

---

# The OTA mechanism

The rest of this document explains how an OTA is staged and flashed on an HP TouchPad.
It was worked out on webOS 3.0.5; **the same mechanism is used on CE 3.1.0 and later** — the
`ota-scripts`, session files and update ramdisk are unchanged there, confirmed present
and untouched in the 3.1.0 image.

⚠️ **This describes the manual path, without signature verification.** It is the right
reference for understanding and debugging the mechanism. Anything delivered to real
users must additionally satisfy the trust model in `OTA-3.1.0.md` Part II.

## Prerequisites

### Hardware
- HP TouchPad with webOS 3.0.5 installed
- USB cable for novacom connection
- Computer running macOS, Linux, or Windows

### Software
- **novacom** - Palm/HP's USB communication tool
  - macOS: Install from Palm SDK or use Homebrew
  - Linux: Available in Palm SDK
  - Windows: Install Palm SDK or standalone novacom driver
- **Python 3.8+** (for the update server)
- **ar, tar, gzip** (standard Unix tools for building packages)

### Verify Connection

```bash
# Check that your TouchPad is connected and recognized
novacom -l

# Expected output:
# 12345 abc123... usb topaz-linux
```

If no device appears:
1. Enable Developer Mode on the TouchPad (Settings > Device Info > tap webOS version 5 times)
2. Reconnect USB cable
3. On macOS/Linux, ensure novacomd is running: `novacomd &`

---

## What a payload is, and what it can do

**Read from `mmipkg` source on 2026-09-04** (contributed by the image-build side,
`webos-doctor-ce`). `/usr/bin/mmipkg` in the shipped rootfs is a `/bin/sh`
script, so everything below is read rather than inferred. This section exists
because several of these properties are surprising and at least two of them can
destroy a device's app if a payload author assumes Debian/ipkg semantics.

### There is no image, and there are no deltas

Palm's OTA never shipped a system image — the Doctor is the full-image path.
An OTA is a **list of `.ipk` files** installed by `PmUpdater` → `mmipkg`. There
is no binary-delta support anywhere in the mechanism: a file inside an ipk is
replaced whole.

"Delta" therefore exists only at **package granularity** — you ship the packages
that changed, containing the files that changed. The useful consequence:

> **A single-file payload is the natural unit here, not a special case.**
> An 8 KB update is an 8 KB update.

### Two install tiers, and only one is dangerous

| Tier | What it does | Risk |
|------|--------------|------|
| **Armed flash** | `make-update-uimage` builds a ~9 MB ramdisk, repoints `/boot/uImage`, reboots; `PmUpdater` installs against `/rootfs`; reboots back. Requires an `updatefsinfo` package. | Open item #4 — unverified end to end. Can strand a device. |
| **Running-system install** | `ipkg`/`mmipkg install` on the live device. No ramdisk, no `/boot`, no reboot. | Bounded by what the payload touches. |

The ramdisk tier exists for what a running system cannot do: replace files that
are held open, and — on CE 3.1.0 — write a read-only root. **A payload that needs
neither should not pay the brick risk for them.** See "the hotpatch tier" in
`OTA-3.1.0.md`, Part VII.

### The payload can write anything

`unpack_data` is:

```sh
ar p $ipk data.tar.gz | tar -C $ROOT_DIRECTORY -xvzf -
```

No path filter, no allowlist, no protection of system directories.
`/usr/palm/applications/`, `/usr/bin/`, `/etc/event.d/`, `/usr/share/ls2/` are
all writable. **Yes, an OTA can replace a stock system app** — that is how the
`UpdatesApp.js` reroute could eventually ship as a payload instead of a runtime
patch.

In the ramdisk, `ota.sh:239-244` mounts store-root **rw** at `/rootfs`, along
with `/boot`, `/var`, `/var/log`, `/var/lib/update` and `/media/internal`. So
**CE 3.1.0's read-only rootfs is not a factor on the armed-flash path** — no
remount, no lock. This is the one thing the heavy tier does better than a
running-system hotpatch.

Caveat for apps specifically: replacing an app's files is not enough to replace
the app. webOS serves cached app code, so a payload touching
`/usr/palm/applications/<id>/` must also bump that app's `appinfo.json`
`version`. The post-update reboot handles the restart; it does not handle the
cache. (Same lesson as `otaready-app/CLAUDE.md` #1.)

### `postinst` runs — and a nonzero exit fails the whole update

`install_ipk` runs `preinst` → unpack → `postinst`. In the ramdisk `run_script`
invokes it as:

```sh
chroot /rootfs /usr/lib/ipkg/info/<pkg>.postinst
```

and immediately after:

```sh
if [ $? -ne 0 ]; then fail "Script execution failed"
```

Three consequences:

- **Every OTA `postinst` must `exit 0` unconditionally.** `mmipkg` is much less
  forgiving than the `ipkg` that Preware drives; a postinst that returns nonzero
  aborts the update rather than logging a warning.
- It runs **as root, chrooted into the target rootfs** — correct paths, full
  privileges, and `/media/internal` is mounted.
- It runs with **no Luna, no D-Bus, and the ramdisk's upstart rather than the
  target's.** `luna-send` and `start <job>` do nothing useful there. Rely on
  `post-update`'s reboot for anything service-shaped.

### An upgrade is remove-then-install, NOT an overlay

**This is the trap most likely to cost someone an app.** `install_prep`
classifies a package as *existing* iff `/usr/lib/ipkg/info/<pkg>.control` is
present. If it is, `install_ipk` calls `remove` **first** — which runs `prerm`
and deletes every file listed in the old `.list`, protected only by files owned
by packages *not* in the update. Only then does it unpack the new data.

> A partial single-file ipk claiming an **existing** package id **deletes the
> rest of that package**.

A single-file payload is safe only as a **new package id**, or as a **complete
replacement** of an existing one. Check `/usr/lib/ipkg/info/` on a target device
before assuming which case you are in — and note that the rootfs database
(`/usr/lib/ipkg`, what `mmipkg` uses) is **not** the same as the cryptofs one
(`/media/cryptofs/apps/usr/lib/ipkg/status`, what Preware reads). A package can
be registered in one and absent from the other.

*Worked example:* CE 3.1.0 bakes `com.webosarchive.usbsettings` as files under
`/usr/palm/applications/` but registers it in **neither** database. A payload
for it is therefore classified as new, skips the remove step, and cleanly
overlays the baked files. That is a safe accident, not a design — and it would
silently invert if a future image seeded the rootfs database.

### Self-replacement is safer here than in a hotpatch

`mmipkg`'s remove-then-unpack path **unlinks** the old file and creates a new
one, so a running `/bin/sh` script keeps its old inode open and finishes
cleanly. This is the `rename(2)` property M13 asks for, obtained for free.

The hazard M13 warns about is therefore specific to the **running-system tier**:
a hotpatch that `cp`s over a live shell script truncates and rewrites the *same*
inode, and the running daemon executes garbage from wherever it had reached.
Always stage to a temporary file on the same filesystem and `mv` into place.

### Two ordering accidents worth knowing

1. **`updatefsinfo` is first by luck, not by rule.**
   The 1.x helper `direct-update.sh:create_session_files` (removed; in git history) ordered the package list with
   `sort -r`, so `updatefsinfo` lands first only because `u` sorts after `c`. A
   package named later in the alphabet would silently displace it and fail
   `make-update-uimage`. This deserves an explicit ordering rule before the
   first real armed flash.
2. **`generate_status` rewrites the whole status file.** After every install it
   deletes `/usr/lib/ipkg/status` and regenerates it from the info directory,
   stamping every package `Status: install user installed`. Harmless in practice,
   but it means an OTA relabels packages it never touched.

Also note that overwriting a baked rootfs file diverges its ipkg `md5sums`
(as already recorded for `UpdatesApp.js` in `OTA-3.1.0.md`). Harmless at
runtime — `integcheck` is a flash-time gate — but it surfaces for anyone who runs
it afterwards.

---

## Part 1: Creating Update Packages

### Package Structure

Each package needs:
```
my-package/
├── CONTROL/
│   ├── control      # Package metadata (required)
│   └── postinst     # Post-install script (optional)
└── data/
    └── ...          # Files to install (mirrors device filesystem)
```

### Step 1.1: Create the Control File

Create `CONTROL/control` with these **required** fields:

```
Package: com.example.mypackage
Version: 1.0.0
Section: misc
Priority: optional
Architecture: all
Installed-Size: 1
Maintainer: Your Name <you@example.com>
Description: Brief description of your package.
webOS-Package-Format-Version: 2
webOS-Packager-Version: 3.0.5b38
```

**Important Notes:**
- `webOS-Package-Format-Version: 2` and `webOS-Packager-Version: 3.0.5b38` are **required** - without them, ipkg will reject the package
- Use `com.palm.*` prefix for packages that need system privileges
- `Installed-Size` can be approximate (in KB)

### Step 1.2: Create Post-Install Script (Optional)

Create `CONTROL/postinst` if you need to run commands after installation:

```bash
#!/bin/sh
# Post-install script

echo "Package installed successfully!"

# Example: Create a marker file
echo "Installed on $(date)" > /media/internal/my-package-installed.txt

exit 0        # MANDATORY -- see below
```

Make it executable: `chmod +x CONTROL/postinst`

⚠️ **The trailing `exit 0` is not boilerplate.** `mmipkg` aborts the entire
update if a maintainer script returns nonzero, so an OTA postinst must exit 0 on
every path, including its failure paths. It also runs chrooted in the update
ramdisk with no Luna, no D-Bus and no target upstart. See
"What a payload is, and what it can do" above before writing one.

### Step 1.3: Add Data Files

Place files in `data/` mirroring the device filesystem:

```
data/
├── media/
│   └── internal/
│       └── myfile.txt          # Installs to /media/internal/myfile.txt
└── usr/
    └── palm/
        └── applications/
            └── com.example.app/
                └── ...          # Installs to /usr/palm/applications/...
```

### Step 1.4: Build the IPK

```bash
#!/bin/bash
# build-package.sh

PACKAGE_DIR="my-package"
WORK_DIR="/tmp/ipk-build"
OUTPUT="my-package_1.0.0_all.ipk"

# Clean and create work directory
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

# Create debian-binary
echo "2.0" > "$WORK_DIR/debian-binary"

# Create control.tar.gz (MUST have ./ prefix and root ownership)
cd "$PACKAGE_DIR/CONTROL"
tar --uid=0 --gid=0 -czf "$WORK_DIR/control.tar.gz" ./control ./postinst 2>/dev/null || \
tar --uid=0 --gid=0 -czf "$WORK_DIR/control.tar.gz" ./control

# Create data.tar.gz (MUST have ./ prefix and root ownership)
cd "$PACKAGE_DIR/data"
tar --uid=0 --gid=0 -czf "$WORK_DIR/data.tar.gz" ./*

# Create IPK (order matters!)
cd "$WORK_DIR"
ar -cr "$OUTPUT" debian-binary control.tar.gz data.tar.gz

echo "Created: $OUTPUT"
echo "Size: $(stat -f%z "$OUTPUT" 2>/dev/null || stat -c%s "$OUTPUT") bytes"
echo "MD5: $(md5sum "$OUTPUT" | cut -d' ' -f1)"
```

### Step 1.5: Create updatefsinfo Package

**Every OTA update requires an `updatefsinfo` package** that tells the system about the update. Create this structure:

```
updatefsinfo/
├── CONTROL/
│   └── control
└── boot/
    └── updatefs-info
```

`CONTROL/control`:
```
Package: updatefsinfo
Version: 1.0.0
Section: misc
Priority: optional
Architecture: all
Installed-Size: 1
Maintainer: Your Name <you@example.com>
Description: Update filesystem info for OTA update.
webOS-Package-Format-Version: 2
webOS-Packager-Version: 3.0.5b38
```

`boot/updatefs-info`:
```
UPDATEFS_VERSION=1.0.0
UPDATEFS_KB=15000
UPDATEFS_INODES=640
```

---

## Part 2: Staging the Update

### Step 2.1: Upload Packages to Device

```bash
# Upload updatefsinfo (required for OTA)
novacom put file:///var/lib/update/updatefsinfo_1.0.0_all.ipk < updatefsinfo_1.0.0_all.ipk

# Upload your package(s)
novacom put file:///var/lib/update/com.example.mypackage_1.0.0_all.ipk < com.example.mypackage_1.0.0_all.ipk
```

Verify uploads:
```bash
novacom run "file://bin/ls -la /var/lib/update/"
```

### Step 2.2: Create Session Files

The OTA system requires specific session files. **Filenames must exactly match the uploaded packages!**

```bash
# Create update_list.txt (used by make-update-uimage)
echo '/var/lib/update/updatefsinfo_1.0.0_all.ipk
/var/lib/update/com.example.mypackage_1.0.0_all.ipk' | novacom put file:///var/lib/software/SessionFiles/update_list.txt

# Create install_list.txt (used by PmUpdater in OTA ramdisk)
# Note: Paths have /rootfs prefix because ramdisk mounts rootfs there
echo '/rootfs/var/lib/update/updatefsinfo_1.0.0_all.ipk
/rootfs/var/lib/update/com.example.mypackage_1.0.0_all.ipk' | novacom put file:///var/lib/software/SessionFiles/install_list.txt

# Set the updating flag
echo '1' | novacom put file:///var/lib/software/updating
```

Verify session files:
```bash
novacom run "file://bin/cat /var/lib/software/SessionFiles/update_list.txt"
novacom run "file://bin/cat /var/lib/software/SessionFiles/install_list.txt"
novacom run "file://bin/cat /var/lib/software/updating"
```

### Step 2.3: Clear Old Status (Optional)

```bash
novacom run "file://bin/rm /var/lib/software/SessionFiles/update_status.txt" 2>/dev/null
```

---

## Part 3: Deploying the Update

### Step 3.1: Create Update Image

This builds a ~9MB ramdisk that the device boots into for the update:

```bash
novacom run "file:///usr/share/ota-scripts/make-update-uimage"
```

This takes 30-60 seconds. When complete, verify:
```bash
novacom run "file://bin/ls -la /boot/uImage /boot/update-uimage"
```

You should see:
- `/boot/update-uimage` - The new update ramdisk (~9MB)
- `/boot/uImage` - Symlink pointing to `update-uimage`

### Step 3.2: Reboot into Update Mode

```bash
novacom run "file://sbin/reboot"
```

**What happens next:**
1. Device reboots into the update ramdisk
2. Pre-update script saves user data
3. PmUpdater installs your packages
4. Post-update script runs cleanup
5. Device reboots back to normal

### Step 3.3: Monitor Progress (Optional)

If you reconnect via novacom while in update mode:

```bash
# Check if still in OTA ramdisk (look for /rootfs mount)
novacom run "file://bin/mount" | grep rootfs

# Check progress (0=start, 1=pre-update done, 2=install done)
novacom run "file://bin/cat /rootfs/var/log/progress"

# Check installation status
novacom run "file://bin/cat /rootfs/var/lib/software/SessionFiles/update_status.txt"
```

---

## Part 4: Verifying the Update

After the device reboots normally:

### Check Package Status

```bash
# Verify package is installed
novacom run "file://usr/bin/ipkg status com.example.mypackage"

# Or using mmipkg
novacom run "file://usr/bin/mmipkg status com.example.mypackage"
```

### Check Your Files

```bash
# Example: Check if your files were installed
novacom run "file://bin/cat /media/internal/my-package-installed.txt"
```

### Check Update Status

```bash
novacom run "file://bin/cat /var/lib/software/SessionFiles/update_status.txt"
```

Success looks like:
```
0
updatefsinfo_1.0.0_all
0
0
com.example.mypackage_1.0.0_all
0
0
```

---

## Troubleshooting

### "E0060004" - Package Installation Failed

**Cause:** Usually a filename mismatch between session files and actual files.

**Fix:**
1. Check filenames match exactly:
   ```bash
   novacom run "file://bin/ls /var/lib/update/"
   novacom run "file://bin/cat /var/lib/software/SessionFiles/update_list.txt"
   ```
2. Re-create session files with correct filenames

**Test package directly:**
```bash
novacom run "file://usr/bin/mmipkg install /var/lib/update/your-package.ipk"
```

### Device Stuck in OTA Ramdisk

**Symptoms:** Device shows HP logo, novacom shows device but filesystem looks different.

**Fix:**
```bash
# Restore normal boot
novacom run "file://bin/ln -sf uImage-2.6.35-palm-tenderloin /rootfs/boot/uImage"

# Clear updating flag
novacom run "file://bin/rm /rootfs/var/lib/software/updating"

# Reboot
novacom run "file://sbin/reboot"
```

### Package Rejected by ipkg

**Symptoms:** `ipkg install` returns error 22 or "invalid package"

**Fix:** Ensure control file has required webOS fields:
```
webOS-Package-Format-Version: 2
webOS-Packager-Version: 3.0.5b38
```

### make-update-uimage Fails

**Check the log:**
```bash
novacom run "file://bin/cat /var/log/uimage.log"
```

**Common issues:**
- updatefsinfo package missing or not first in update_list.txt
- Insufficient space in /boot or /tmp
- Corrupt package file

---

## Quick Reference

### File Locations

| File | Purpose |
|------|---------|
| `/var/lib/update/*.ipk` | Downloaded/staged packages |
| `/var/lib/software/SessionFiles/update_list.txt` | Package paths (no /rootfs) |
| `/var/lib/software/SessionFiles/install_list.txt` | Package paths (with /rootfs) |
| `/var/lib/software/updating` | Flag file (1=pending) |
| `/var/lib/software/SessionFiles/update_status.txt` | Results |
| `/boot/update-uimage` | OTA boot ramdisk |
| `/boot/uImage` | Symlink to active kernel |
| `/var/log/uimage.log` | make-update-uimage log |

### Useful Commands

```bash
# List installed packages
novacom run "file://usr/bin/ipkg list_installed"

# Get package info
novacom run "file://usr/bin/ipkg info packagename"

# Install package directly (no OTA)
novacom run "file://usr/bin/ipkg install /path/to/package.ipk"

# Remove package
novacom run "file://usr/bin/ipkg remove packagename"

# Check device storage
novacom run "file://bin/df -h"
```

---

## Alternative: Direct Installation (No OTA)

For quick testing, skip the full OTA process:

```bash
# Upload package
novacom put file:///tmp/mypackage.ipk < mypackage.ipk

# Install directly
novacom run "file://usr/bin/ipkg install /tmp/mypackage.ipk"

# Or using mmipkg (what PmUpdater uses)
novacom run "file://usr/bin/mmipkg install /tmp/mypackage.ipk"
```

This installs immediately without rebooting, but doesn't go through the full OTA validation/backup process.
