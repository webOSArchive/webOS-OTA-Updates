# OTA on webOS 3.0.5

**The single reference for getting a community OTA onto a TouchPad still running
webOS 3.0.5** — the heterogeneous, unmanaged device population.

Consolidates `howto-ota-3.0.5.md` and `plan.md` (2026-08-30). Both are superseded and
removed; **edit this document instead.** `plan.md`'s durable protocol research is
preserved in Appendix A; its 2025-12-31 implementation plan targeted the native
OMA-DM path, which was subsequently proven a dead end, and is not carried forward —
see Appendix A's warning before acting on anything there.

Companions: `OTA-3.1.0.md` for the community OS release · `OTA-UPDATE-GUIDE.md` for
the low-level flash mechanics both releases share.

**Status legend used throughout:**

| Mark | Meaning |
|------|---------|
| ✅ | Works today, proven on hardware |
| 🔨 | Has to be built or changed first |
| ⛔ | Blocked on a decision |

**Where this stands right now:** the delivery chain has been proven end to end on
hardware *except the final flash*, and there is no signing yet. You cannot ship a
real OTA to real users today. §7 lists exactly what is missing.


---

## 1. Why 3.0.5 is the hard case

3.0.5 devices are a **heterogeneous, unmanaged population**. Every one of them has
been modified differently over fifteen years, and none of them ship anything that
knows how to take a community update. So before an OTA can reach a 3.0.5 device,
something has to be installed on it first. That something is the **OTA Ready** app.

The three axes that vary in the field:

| Axis | Meaning |
|------|---------|
| **L** | LunaCE launcher installed, or stock |
| **T** | Community TLS 1.3 stack at `/usr/lib/ssl11`, or 2009-era crypto only |
| **Q** | nizovn QupZilla browser installed, or not |

The one that matters for delivery is **T**. A device without the modern TLS stack
**cannot reach an HTTPS server at all** — its OpenSSL is 0.9.8k from 2009. Today
those devices are told to install the TLS suite manually from Preware before they
can do anything else. See §6 for a change that may remove that requirement.

---

## 2. The chain, end to end

```
   YOU                          SERVER                       DEVICE
   ───                          ──────                       ──────
1. build IPK payload
2. sign it (offline key)  ──►  publish manifest + .sig
                               publish packages
3. edit offer.json        ──►  git push, server reloads
                                       │
                                       │  device asks: "anything for me?"
                                       ◄──────────────────────────  OTA Ready app
                                       │                            (daemon polls)
                                       ├──►  offer + signed manifest
                                                                    │
                                                       4. verify signature
                                                       5. download + check sha256
                                                       6. stage SessionFiles
                                                       7. ARMED: flash + reboot
                                                          into the OTA ramdisk
                                                       8. install, reboot back
```

Steps 1–3 are yours. Steps 4–8 happen on the device, driven by the daemon that the
OTA Ready app installs.

---

## 3. One-time setup

### 3.1 The signing key ✅

Already generated. RSA-4096, SHA-256 signatures, chosen specifically because it
verifies under the **stock 2009 OpenSSL** that every 3.0.5 device has — no
dependency on the TLS suite being installed first.

- Public half: `keys/ce-ota-signing.pub` (in this repo)
- Fingerprint: `keys/ce-ota-signing.pub.sha256`
- Private half: **on the signing host only**, never in this repo

The private key is the whole trust anchor. If it leaks, anyone can push root code to
every device. If it is lost, you cannot sign updates any more and recovery means
re-flashing every device by hand. Back it up, encrypted, in more than one place.

### 3.2 The server ✅

Running at `https://swupdate.webosarchive.org` (FastAPI, systemd, git-to-deploy).
Full instructions in `webos-update-server/DEPLOY.md`. You only touch this again if
the host changes.

### 3.3 The OTA Ready app, published to App Museum II ✅

This is how the client reaches devices. Museum installs run through Preware, which
runs our `postinst`, which installs the daemon and helpers. Published under the exact
name **"OTA Ready"** — the app's own self-update check matches on that string, so
renaming it silently breaks upgrades for everyone who already has it.

---

## 4. Per-release: building and signing a payload

### 4.1 Build the IPKs ✅

Payload packages live in `webos-update-server/packages/`. Sources under
`packages/ota-build/<name>/` with a `CONTROL/` directory; `packages/build-ota.sh`
assembles them into properly-formed webOS IPKs (root ownership, `./` prefixes,
`webOS-Package-Format-Version: 2` — all of which ipkg requires or it silently
refuses the package).

```bash
cd webos-update-server/packages
./build-ota.sh
```

**Know exactly what your packages do to the rootfs before going further.** The OTA
runs as root, rewrites `/boot/uImage`, and reboots into a ramdisk to install. There
is no undo short of a Doctor flash.

### 4.2 Sign the manifest and packages 🔨

The signing scheme is designed but **not yet implemented in the daemon** (see
`OTA-3.1.0.md` M10). Two tiers:

- **Manifest** — lists each package, its `sha256`, its download URL, and a
  monotonically increasing `serial`. **Signed offline** with the private key.
- **Offer** — the "is there an update for you" answer. Dynamic, per-device, served
  over TLS. **Not** a trust anchor.

Payload URLs come from the *signed manifest*, never from the offer. That is what
stops a compromised server from pointing devices at someone else's payload.

On the signing host, per release:

```bash
openssl dgst -sha256 -sign ce-ota-signing.key -out manifest.sig.bin manifest.json
openssl base64 -in manifest.sig.bin -out manifest.json.sig
```

Bump `serial` every release. The device refuses any manifest whose serial is not
higher than the last one it installed — that is what prevents an attacker replaying
an old, known-vulnerable update.

### 4.3 Publish 🔨 (server side of signing not built yet)

Copy the packages, `manifest.json` and `manifest.json.sig` to the server, then edit
**`offer.json`** — one file — and `git push`. The server re-reads it per request, so
no restart:

```json
{
  "status": "Available",
  "version": "webOS Community Update 1.0",
  "size": "12",
  "installTime": "5",
  "networkAvailable": true,
  "priority": "optional"
}
```

Set `{"status": "UpToDate"}` to withdraw the offer from everyone instantly. That is
your kill switch — know where it is before you need it.

---

## 5. Getting the client onto a device

This is the part unique to 3.0.5, and it needs the device owner to act.

1. **The owner installs "OTA Ready" from App Museum II** (via Preware). ✅
2. Preware runs the `postinst`, which installs `/usr/bin/ota-fingerprint`, the root
   daemon `otaready-daemon`, the direct-update helper, an upstart job, and registers
   the command-bridge service on the Luna bus. ✅
3. **The device must be rebooted once.** ✅ (unavoidable)

   The status display works immediately, but the *first action* the owner takes —
   "Use New Update Server", Install, Reset — will fail with "couldn't reach the OTA
   Ready helper service" until one reboot. This is not a bug we can fix: `ls-hubd`
   caches its service registry at boot, so a service installed into a running system
   is invisible until the next boot. It is one time only and survives later upgrades.

   **This is a known beta stumbling block.** Tell people about the reboot up front;
   several testers read the error as a crash.

4. **The owner taps "Use New Update Server".** ✅ This patches the stock System
   Updates app in place so it reads our offer instead of calling Palm's long-dead
   servers. The screen goes dark for several seconds and open apps close — the app
   warns about this first, because the patch deliberately restarts Luna.

5. From then on, **System Updates behaves normally** — Check Now, an offer, Install.
   The owner does not need to open OTA Ready again.

---

## 6. The TLS problem, and a change worth making 🔨 ⛔

Roughly half the baselines (**C, D, G, H**) have no modern TLS. They physically
cannot open an HTTPS connection to the update server, so today they are refused with
`INSTALL_TLS` and the owner must install the community TLS suite from Preware first.
That is a real drop-off point: a manual prerequisite before the thing that was
supposed to be automatic.

**Because payloads are signed offline, the transport does not need to be trusted.**
A signed manifest and payload can be served over **plain HTTP** to those devices
safely — an attacker on the wire can block or corrupt a download, but cannot forge a
signature, and a corrupted download fails its `sha256` check. Nothing in the payload
is secret, so there is nothing to keep confidential.

If adopted, this removes the manual TLS step from the 3.0.5 bootstrap entirely.
**Awaiting a decision from the image-build side** — see `OTA-3.1.0.md` Part II.

---

## 7. What is missing before you can ship to real users

In dependency order. Nothing below is optional.

1. **⛔ Signing is not implemented on the device.** The daemon does not yet verify
   anything (M10). Until it does, an OTA is an unauthenticated root code path — do
   not ship one.
2. **⛔ The armed flash has never been verified end to end.** `arm-install` →
   `make-update-uimage` → reboot into the OTA ramdisk → install → reboot back. Every
   earlier stage is proven; this last one has only ever run with the safety catch
   engaged. It must be proven on an expendable device before any user sees it.
3. **🔨 There is no real payload.** The server hosts test packages and a placeholder
   offer ("webOS Community OTA Test 0.1").

   The payload wishlist (LunaCE, the TLS suite, UberKernel, the browser) has been
   folded into the **CE 3.1.0 image** rather than remaining a set of separate OTAs.
   So those are now image *contents*, and the natural first real payload for a 3.0.5
   device is plausibly **3.0.5 → 3.1.0 itself**. That is what makes the version fix
   matter: until the device sends `PRODUCT_VERSION_STRING` instead of its product
   name, the server cannot express "offer this only to devices below 3.1.0". See
   `OTA-3.1.0.md` M6.
4. **🔨 Server-side eligibility.** Device eligibility is currently decided *on the
   device*, which means changing the rules means shipping a new app. Moving the
   decision to the server makes it a `git push`.
5. **🔨 OTA Ready v2.** The current app was a first attempt. v2 should report facts
   and let the server decide, expose a working **revert** (today a stuck tester's
   only escape is a Doctor flash), and handle the mandatory reboot gracefully
   instead of failing with an error.

---

## 8. Verifying it worked

On the device, over novacom:

```sh
# what the device thinks it is
/bin/sh /usr/bin/ota-fingerprint --json

# what the daemon is doing
tail -30 /var/log/otaready-daemon.log

# the offer the device is actually being served
cat /media/internal/.otaready/offer.json

# can it even reach the server?
curl -s -m 20 https://swupdate.webosarchive.org/api/updates/offer
```

Server side: `GET /api/stats` shows per-device traffic — build, baseline, checks,
downloads, last-seen. Useful for confirming a beta tester's device actually called in.

**The safety catch:** the irreversible flash only runs if
`/media/internal/.otaready/arm-install` exists. It is absent by default, so you can
exercise the entire chain — offer, download, staging — without any risk of a reboot
or a flash. Do that first, every time, on every new payload.

---

## 9. Troubleshooting

| Symptom | Cause |
|---------|-------|
| "Couldn't reach the OTA Ready helper service" | The one-time reboot hasn't happened yet (§5.3) |
| App shows a status but never an offer | Device is `ready:false` — check the fingerprint's `action` field |
| Device never contacts the server | No modern TLS (`T=0`), so HTTPS is impossible (§6) |
| Offer never changes after editing `offer.json` | A local override is masking it — check for `test-offer.json` or `server-url` in `.otaready/` |
| "No more updates" when you expect one | The `.installed` latch is set; remove it or use the app's **Reset OTA Test** |
| Changed the app's JS but the old behaviour persists | webOS caches app code — you must bump the version in `appinfo.json` |

---

# Appendix A — Native OMA-DM: protocol reference and why it was abandoned

> **⚠️ Read this warning first.** The material below documents the *original* approach:
> replacing Palm's OMA Device Management server so the stock updater would talk to us.
> **That path is a proven dead end.** The `palm://com.palm.update` daemon is
> carrier-gated and never reaches a server on a Wi-Fi TouchPad. The former `plan.md`
> ended with "Immediate Priority: Fix HMAC-MD5 Authentication" — **do not act on
> that.** Authentication was never the real blocker; the transport was.
>
> Everything shipping today uses the direct-update REST path instead. This appendix is
> kept for two reasons: the protocol research is hard-won and may matter if anyone
> revisits the stock client (see `OTA-3.1.0.md`, "Why not just ship 3.1.0 pointing at
> the new update server?"), and the DmTree discovery below cost real debugging time.

## The discovery worth keeping: DmTree.xml exists in THREE places

This is the single most valuable finding from the OMA-DM work, and it is not
documented anywhere else:

| File | Purpose | Writeable |
|------|---------|-----------|
| `/usr/share/omadm/DmTree.xml` | Source/template | No (read-only `/`) |
| `/var/lib/software/DmTree.xml` | **Runtime config — what OmaDm actually reads** | Yes |
| `/var/lib/software/DmTree.backup.xml` | Backup; OmaDm regenerates from this | Yes |

**OmaDm reads `/var/lib/software/DmTree.xml` at runtime, not `/usr/share/omadm/DmTree.xml`.**
Editing only the `/usr/share/` copy — the obvious one, and the one every guide names —
leaves the device still pointing at Palm's dead URL. Anyone repointing the stock
client must change all three.

## Protocol reference

Original endpoint: `https://ps.palmws.com/palmcsext/swupdateserver`
(Palm's OTA host was `omadm.swupdate.palm.com`.)

- **Transport:** HTTPS 443 or HTTP
- **Encoding:** SyncML 1.2, WBXML (binary) or XML
- **Auth:** HMAC-MD5, header
  `x-syncml-hmac: algorithm=MD5, username=<user>, mac=<base64>`
- **Credentials:** `guest` / `guestpassword` (hardcoded defaults)
- **Staging:** `/var/lib/update/`, session state `/var/lib/software/SessionFiles/`

### Session flow

```
Device                                    Server
   |  1. PKG#1: SessionInit (Alert 1201)     |
   | ───────────────────────────────────────>|
   |  2. PKG#2: Status + Get DevInfo/Build   |
   |<─────────────────────────────────────── |
   |  3. PKG#3: Results + Client Status      |
   | ───────────────────────────────────────>|
   |  4. PKG#4: Replace PkgURL + Exec        |
   |<─────────────────────────────────────── |
   |  5. PKG#5: Acknowledge + Final          |
   | ───────────────────────────────────────>|
   |  6. Device downloads IPK from PkgURL    |
   | ═══════════════════════════════════════>|
```

Status codes: `212` authentication accepted · `401` unauthorized · `407`
authentication required.

### DM tree paths

- `./DevInfo/*` — DevId, Man, Mod, FwV, SwV, HwV
- `./Software/Build` — current OS build
- `./Software/Package/*` — PkgURL, PkgName, PkgVersion, PkgSize
- `./Software/Operations/DownloadAndInstall` — Exec target

### Binaries worth knowing about

- `/usr/bin/OmaDm` — the OMA-DM client
- `/usr/bin/UpdateDaemon` — update orchestration. Resolves its server URL at runtime
  via `palm://com.palm.accountservices/getServerUrl`, defaulting to
  `omadm.swupdate.palm.com` — i.e. it is *not* hardcoded to a dead host. See
  `OTA-3.1.0.md` Appendix B for why that still isn't the easy win.
- `/usr/share/ota-scripts/` — the install scripts, documented in `OTA-UPDATE-GUIDE.md`

## Implementation status when the path was abandoned

The server in `webos-update-server/` still contains a working WBXML codec, SyncML
parser/builder, session management and package hosting. What never worked was
HMAC-MD5 authentication (device returned 407/401). It was not pursued, because even a
correct implementation would not have solved the carrier gating.

The endpoint `POST /palmcsext/swupdateserver` remains in the server for reference.
Nothing in the live path uses it.
