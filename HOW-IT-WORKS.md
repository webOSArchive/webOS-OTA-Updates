# How a webOS CE OTA works

An HP TouchPad running webOS CE can now update itself over the air: open System
Updates, tap **Install Now**, and a few minutes later it restarts on the new version
with apps, accounts, mail and files intact. HP shut down its update servers in 2012,
so none of this worked for over a decade. This page explains what happens at each
step, and what we had to figure out to make it work.

It's written for developers who know Linux basics (packages, shell scripts, HTTP).
You don't need to know webOS internals.

---

## The big picture

```
 Build machine                    Update server                     TouchPad
 ─────────────                    ─────────────                     ────────
 old image + new image            swupdate.webosarchive.org         OTA Ready daemon
        │                                │                                │
        ▼                                │                                │
 make-payload.py ─► payload .ipk ───────►│◄──── "I'm build 600070" ───────┤
        │                                │───── "here's a manifest" ─────►│
        ▼                                │                                │ verify signature
 sign-manifest.py ─► manifest + .sig ───►│◄──── download payload ─────────┤ check device
                                         │                                │ arm the update
                                                                          ▼
                                                                  reboot into the
                                                                  update ramdisk
                                                                          │
                                                                          ▼
                                                                  install payload,
                                                                  reboot into new OS
                                                                          │
                                                                          ▼
                                                                  ce-ota-finish
                                                                  (first boot)
```

There are four pieces:

1. **The payload generator** (in the webOS CE Doctor project): compares two system
   images and builds one package that turns the old one into the new one.
2. **The update server** (`webos-update-server/`, this repo): decides which devices are
   offered which update, and serves signed manifests and payloads.
3. **OTA Ready** (`otaready-app/`, this repo; in App Museum II): the client on the
   TouchPad. It checks for updates, downloads, verifies, and starts the install.
4. **webOS's own updater**, which is still on every TouchPad: a small boot image (the
   "update ramdisk") that installs packages while the normal OS is not running.

The rest of this page goes through an update in order.

---

## Step 1: Build the payload

### What a webOS update is

You might expect an OS update to be a disk image, or a binary diff. On webOS it is
neither. An update is **a list of `.ipk` packages** (the same simple package format
Preware uses: an `ar` archive holding `control.tar.gz` and `data.tar.gz`). The
updater installs them one after another. There is no support for binary deltas.

So our payload is **one `.ipk`** whose contents are exactly the difference between two
system images:

- every file that is new or changed goes in `data.tar.gz`;
- every file that was removed gets an `rm` in the package's scripts;
- permission, owner and symlink changes are applied by the scripts too.

### How the generator builds it

`make-payload.py` reads both images (the "Doctor" JARs used to flash a TouchPad),
compares every file, and writes:

| Part | What it does |
|------|--------------|
| `preinst` | Runs before unpacking. Removes paths whose type changes, such as a hard link that becomes a plain file. Otherwise unpacking would write *through* the old link and change the file it points to (3.1.0's time zone files are hard links to each other) |
| `data.tar.gz` | The new and changed files, at their full paths |
| `postinst` | Removes deleted files and directories, fixes modes and owners, then removes the package's own records so it leaves no trace |

Then it **proves the payload is right before writing it**: it simulates "old image +
payload" in memory and compares the result with the new image, file by file. If even
one file differs, it refuses to write anything. Every payload we ship has passed this
check ("converges: old image + payload == new image, all 22050 members").

Sizes, for a sense of scale:

| Route | Payload |
|-------|---------|
| 3.1.0 → 3.2.0 (a whole release) | 49.5 MB ipk, about 1,400 changed paths |
| 3.2.0 build 600119 → 600120 (a bug fix) | 1.9 MB ipk, 13 changed paths |

### Things we had to learn here

- **An upgrade is remove-then-install.** The installer (`mmipkg`, a shell script on
  the device) treats a package as already installed if its `.control` file exists, and
  then *removes every file of the old version* before unpacking the new one. A payload
  that reused an existing package name would delete that package's other files. So
  each payload uses a fresh package name, and leaves nothing behind afterwards.
- **A failing script aborts the whole update.** If any `postinst` exits non-zero, the
  updater stops. Every payload script must end with `exit 0`, and check its own work
  instead of relying on exit codes.
- **No services while installing.** The scripts run inside the update ramdisk with
  the new system mounted at `/rootfs`. There is no Luna, no system bus, no apps. Work
  that needs the running system has to wait for the first boot (step 6).
- **Some files aren't in the image at all.** The Doctor installs a few packages from a
  separate archive at flash time (ringtones and wallpapers, for example). The
  generator reads those too. 3.1.0 also deleted those files after first boot, so the
  payload for 3.1.0 devices puts them back. Without them, a later Full Erase brings the
  device back with no ringtones.

---

## Step 2: Sign and publish

The update installs as root and replaces system files, so the device must be able to
tell that an update really came from us.

`sign-manifest.py` writes a small JSON **manifest** for each payload:

```json
{
  "name": "600070-600120",
  "from": { "buildmark": "600070", "version": "webOS CE 3.1.0" },
  "to":   { "buildmark": "600120", "version": "webOS CE 3.2.0" },
  "payload": { "file": "...", "url": "/api/ce-ota/payloads/ce-ota-600070-600120.ipk",
               "size": 51891826, "sha256": "...", "md5": "..." },
  "preflight": { "path": "/usr/lib/ipkg/info/org.webosarchive.ce-files.md5sums", "md5": "..." },
  "space": { "rootfs_growth": 58090969, "largest_file": 12833057 },
  "offer": { "title": "webOS CE 3.2.0", "installMinutes": 10 }
}
```

and signs it with an RSA-4096 private key that never leaves the build machine. The
matching **public key is baked into every webOS CE image**, along with a small verify
tool (`ce-ota-verify`). The payload is protected by the sha256 inside the signed
manifest, so the signature covers it too.

Publishing is simple: the manifest and its `.sig` go into this repo (pushing deploys
the server), and the payload is copied to the server by hand.

### Who gets offered what

The server reads `ce-ota/releases.json` on every request:

```json
{"releases": [
  {"manifest": "600070-600120", "devices": ["<device id>", "<device id>"]},
  {"manifest": "600119-600120", "devices": "*"}
]}
```

`"devices"` is either `"*"` (everyone on that build) or a list of device IDs (each
TouchPad's NDUID, which OTA Ready shows under Device Details). That lets us test on a
few devices, then a few testers, then everyone, by editing one file. **The first
release that matches the device's build and admits the device wins**, so the order
of the list matters.

---

## Step 3: Check for an update

OTA Ready installs a small **root daemon** on the TouchPad. Apps on webOS run in a
sandbox and can't read system files or install anything, so the app and System
Updates send commands to the daemon through a tiny bridge service.

The daemon checks at boot and once a week (and whenever you tap Check Now):

```
GET /api/ce-ota/check?build=600070&nduid=<device id>
→ {"status": "Available", "manifest": "600070-600120"}
```

It downloads the manifest and its signature, and checks them **before believing
anything in them**:

1. **Signature**: `ce-ota-verify` checks the manifest against the baked-in public key.
2. **Parse**: a strict parser checks every field against a pattern (no field can carry
   shell code into the scripts that use it).
3. **Device checks**:
   - it is an HP TouchPad (a TouchPad Go is refused);
   - the manifest's `from` build is this device's build;
   - the device really is that build: one file listing the md5 of every CE file must
     match the manifest's `preflight` value;
   - the kernel is the stock one.

If everything passes, System Updates shows the offer with its title and an
**Install Now** button. That's the stock System Updates app from 2011; OTA Ready
patches it to ask the daemon instead of HP's servers.

---

## Step 4: Download and arm

When you tap Install Now, the daemon:

1. checks that first use is finished and no CE first-boot job is still running;
2. checks free space on `/media/internal` (for the download) and on the system
   partition (from the manifest's `space`);
3. checks the battery is at least 50%;
4. downloads the payload to `/media/internal/ce-ota/` (resumable), and checks its
   sha256 against the signed manifest;
5. writes the updater's **session files**: which packages to install, and where;
6. runs `PmUpdater -v`, which validates the session without installing anything;
7. **arms** the update: sets an `updating` flag, runs `make-update-uimage` to build the
   update boot image, points `/boot/uImage` at it, and reboots.

### Things we had to learn here

- **The session files have a strict format.** One of them, `urls`, sounds like a list
  of URLs. It isn't: it needs a header line, a line that is exactly `version=1`, and
  then five lines per package. Get it wrong and the updater says "Empty urls file" and
  refuses. We found this by reading the stock scripts on the device.
- **Validate before you arm.** `PmUpdater -v` catches a bad session on the running
  system, where a mistake is harmless. After arming, a mistake costs a reboot.
- **A first-use trap.** Some CE setup jobs only run once, at the end of first use.
  A device that gets 3.2.0 by update never goes through first use again, so those jobs
  never ran. Their work had to move into the finish step (step 6).

---

## Step 5: The update ramdisk

This is the part from 2011, and it's why the TouchPad can update itself at all.

On reboot, the TouchPad boots the small update image instead of webOS. It:

1. mounts the real system partition **read-write** at `/rootfs` (webOS CE normally
   keeps it read-only; in the ramdisk that doesn't matter);
2. saves some user data aside, just in case;
3. runs `PmUpdater`, which installs each package with `mmipkg`: unpack `data.tar.gz`
   into `/rootfs`, run the scripts with `chroot /rootfs`;
4. checks the filesystems, runs data migrations for the new system, points
   `/boot/uImage` back at the normal kernel, clears the `updating` flag;
5. reboots into the new webOS.

It takes about 100 seconds, with a progress bar on screen.

### Why use the ramdisk at all?

A running system can't safely replace files it is using: Luna (the UI), its
libraries, the shell scripts that are running. The ramdisk installs while none of them
are running. For tiny changes that touch nothing in use, a "hotpatch" on the running
system would work too, but the ramdisk path covers everything, so we use it for all
releases.

### What happens when it fails

We broke updates on purpose to find out:

- If the install fails once (for example, a temporary error), the ramdisk reboots and
  **tries again**, about every 37 seconds. A one-off failure recovers by itself.
- After **four failures** it gives up and deletes the boot image. The TouchPad then
  shows a "!" screen. That sounds bad, but it is recoverable without reflashing: boot
  the old kernel over USB (`novacom boot mem://`), fix the boot link, and reboot.
  `OTA-UPDATE-GUIDE.md` has the steps.
- If the updater refuses a session outright, it restores the normal boot link and
  boots the old OS untouched.

---

## Step 6: First boot and `ce-ota-finish`

The ramdisk can only put files in place. Some things need the running system, so
webOS CE images carry a job, `ce-ota-finish`, that runs on the first boot after an
update. It figures out what changed by comparing the device against the image, so it
doesn't need to know version numbers. It:

- **reinstalls built-in apps that changed.** Apps like Email, Calendar and Photos live
  in an encrypted app area (`cryptofs`) and are installed from bundled packages on a
  fresh flash. An updated device already has old copies, so the finish job reinstalls
  each one whose package changed;
- **places new seed files** in the app area (settings that a fresh flash copies once);
- **cleans up after feed packages** for things the image now includes itself;
- **refreshes caches**, such as the media framework's plugin registry;
- **restores the staged ringtones and wallpapers**;
- **writes the new boot logo** into the bootloader's memory (only the Doctor did that
  before);
- **removes the update boot image** from `/boot` and the downloaded payload.

Each step checks its own result. Only when every step has verified does the job write
"finished and verified" to its log and stop running. If anything couldn't be verified,
it tries again at the next boot.

After that, System Updates opens by itself and says the update was installed.

---

## How we test an update

Before an update is offered to anyone:

1. **The convergence proof** (step 1): old image + payload must equal the new image.
2. **A pre-flight** on a real device, which only reads: does this device really run
   the old image underneath? Files changed by feed packages or by the owner are
   reported, not refused, because the payload only touches the paths it names.
3. **A bench run**: a copy of the server runs on a laptop (`tools/bench-server.py`),
   and a test TouchPad is pointed at it, so production is untouched.
4. **A production run** through App Museum's OTA Ready and Install Now, on test
   devices listed by ID in `releases.json`.
5. **After each update**: compare the device file by file with a fresh flash of the
   new image, check that nothing in `/media/internal` changed, and run the CE
   test suite (more than 170 checks, from boot jobs to opening apps).

Devices we've updated include clean ones and lived-in ones: Exchange mail accounts,
third-party apps, the Qt5 stack, a language pack. Mail, apps and files came through.

---

## Where to look in the code

| What | Where |
|------|-------|
| Server API (release check, manifests, payloads) | `webos-update-server/ce_ota.py` |
| Signing | `webos-update-server/tools/sign-manifest.py` |
| Bench server | `webos-update-server/tools/bench-server.py` |
| On-device signature check | `webos-update-server/device-scripts/ce-ota-verify` |
| The client daemon (check, download, arm) | `otaready-app/org.webosarchive.otaready/device/otaready-daemon` |
| The manifest parser | `otaready-app/org.webosarchive.otaready/device/ota-manifest.js` |
| The patched System Updates | `otaready-app/org.webosarchive.otaready/device/UpdatesApp.patched.js` |
| Flash mechanics and recovery | `OTA-UPDATE-GUIDE.md` |
| Payload generator, finish job | the webOS CE Doctor project: `build/ota/make-payload.py`, `build/full-ce/ce-ota/ce-ota-finish.sh` |
