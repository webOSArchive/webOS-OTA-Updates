# OTA on webOS CE 3.1.0

**The single reference for getting a community OTA onto a device running webOS CE
3.1.0** — the trust model, what the system image bakes, the changes required of the
on-device client, the validation criteria, and the human runbook.

Consolidates three earlier documents (2026-08-30): `OTA-IMAGE-INTEGRATION.md` (the
image spec), `IMAGE-SIDE-DECISIONS.md` (contributed by the image-build side,
`webos-doctor-ce`), and `howto-ota-3.1.0.md` (the human runbook). Those files are
superseded and removed; **edit this document instead.**

Companion: `OTA-3.0.5.md` for the older, heterogeneous device population.
Shared low-level flash mechanics: `OTA-UPDATE-GUIDE.md`.

**Status legend:** ✅ works today, proven on hardware · 🔨 must be built · ⛔ blocked
on a decision.

---

## Status at a glance

**Option A is decided and implemented.** The 3.1.0 image bakes the **trust anchor**
and nothing else of the update client. Build **600070**
(`sha256 392f2122e3bd95f6…`) carries `/usr/share/ce-ota/keys/ce-ota-signing.pub` and
`/usr/bin/ce-ota-verify`, both confirmed in the shipped rootfs, and the build aborts
if the key's fingerprint does not match.

**So a 3.1.0 device is NOT OTA-ready with no user action** — the client still arrives
via Preware, exactly as on 3.0.5. It just has far less work to do when it gets there.
See Part I and Part VI.

Verified against `TestpadE` running `webOS CE 3.1.0` (BUILDNAME `Nova-HP-Topaz`,
BUILDNUMBER 86, BUILDMARK 600067).
---

## Reading the cross-references

This document merges three sources, and their internal numbering is preserved rather
than renumbered, because the image-build side cites these identifiers in their own
repository and in review comments.

- **`M1`–`M14`** (required modifications), **`V1`–`V16`** and **`VS1`–`VS11`**
  (validation) are stable identifiers. They survived the merge unchanged and are the
  safest way to refer to a specific item.
- **`§N` inside Appendix A** refers to the image side's own section numbering in
  their original document, which is reproduced there.
- **`§N` elsewhere**, in text carried over from the former spec, maps to:
  §1 → Part II (trust model) · §2, §3, §4, §5 → Part III (inventory, layout, state
  directory, modifications) · §8 → Part V (validation) · §9 → Part VII (open items).
  The numbered headings themselves have been removed in favour of the Part structure.

---

# Part I — Orientation

## Why 3.1.0 is the easy case

Everything that makes 3.0.5 painful is already solved in 3.1.0, because it ships in
the image:

| Problem on 3.0.5 | On 3.1.0 |
|------------------|----------|
| Might have no modern TLS, can't reach an HTTPS server | ✅ Ships curl 7.88.1 + OpenSSL 1.1.1w |
| Launcher varies wildly, hard to identify | ✅ Known: WebOS Ports LunaCE 5.0.0 |
| Eight different baseline configurations in the field | ✅ One known starting state |
| The population is unmanaged and undocumented | ✅ You built it |

The device is also, usefully, still a **stock-kernel Nova-HP-Topaz** with all the
original OTA machinery (`make-update-uimage`, `ota.sh`, `pre-update`, `post-update`)
present and untouched — so the delivery mechanism 3.0.5 uses works here unchanged.

---

---

## The thing to understand first: what 3.1.0 actually bakes

There were two options. **Option A is the plan of record**, chosen by the image-build
side and agreed by this project.

### Option A — bake the trust anchor only ✅ IMPLEMENTED (build 600070)

3.1.0 ships exactly two small, inert files:

| Path | What it is |
|------|-----------|
| `/usr/share/ce-ota/keys/ce-ota-signing.pub` | The signing public key — the root of trust |
| `/usr/bin/ce-ota-verify` | A ~40-line shell script that verifies a detached signature |

Nothing else. No daemon, no patched System Updates, no bridge service.

**Why:** what ships in the rootfs is **frozen for the life of the release**. The only
ways to change it are a re-flash (which wipes the user's device) or an OTA (which
needs the very mechanism you'd be trying to fix). The armed-flash path has never been
verified end to end and there is no real payload to verify it against, so freezing an
untested irreversible-flash path into a public release is a bad trade.

The key is the exception, because **a trust anchor cannot be delivered over an
untrusted channel**. Ship it in a later update and that first update is
unauthenticated — which is the whole problem. An 800-byte public key costs nothing
and is the one thing that genuinely cannot be added afterwards.

**Consequence: under Option A, a 3.1.0 device still needs the OTA Ready app**, exactly
like a 3.0.5 device does — it just has less work to do when it gets there.

### Option B — bake the whole client, disarmed

3.1.0 would ship the daemon, a pre-patched System Updates, the bridge service and the
helpers, all inert until a signed offer arrives. This is the stated goal: a device
that is OTA-ready with no user action at all.

**Gated on** every validation check in Part V passing on real
hardware first — including the armed flash. Expected in a later CE release, once the
flash path has been proven by real use on 3.0.5.

---

---

# Part II — Principles and trust model

## Principle: the device is the immutable half

We can change the server whenever we like. What ships in the rootfs is frozen for
the life of the release — the only ways to change it are a re-flash (wipes the
user's device) or an OTA (which needs the very mechanism we are baking).

So the rule for the image is:

> **Bake mechanism, never policy. If a decision could ever be made differently,
> it belongs on the server or in a payload — not in the rootfs.**

This is the same instinct behind M2 and M7, extended to everything else.

There is exactly one exception, and it is the reason for Decision 1.

---

---

## Trust model — two-tier, ADOPTED

> The image side reviewed and **adopted** this in preference to their original
> "sign the offer" requirement: signing a per-device response would have put the
> private key on an internet-facing host, violating their own rule. — their §12.

The image side's original requirement (Appendix A) was that the offer be signed, on the grounds that
"signing only the payload leaves the offer spoofable, which is enough to point a
device at an attacker's payload URL." The requirement is right. But signing the
*offer* directly conflicts with M2: the offer is a dynamic, per-device response, so
signing it puts the private key on the internet-facing server — exactly what §1's
own "private half never leaves the signing host" rule forbids.

Proposed resolution — **split trust from eligibility**:

| Tier | Artefact | Trust | Produced |
|------|----------|-------|----------|
| 1 | **Manifest** — package names, `sha256` of each, download URLs, monotonic `serial` | **Offline-signed** with the CE OTA key | On the signing host, committed as a static file |
| 2 | **Offer** — eligibility answer + display strings | TLS only, **not** a trust anchor | Dynamically, per device, by the server |

Rules that follow:

- The daemon installs **only** packages named in a manifest carrying a valid
  signature from the baked key, and only when each downloaded file's `sha256`
  matches the manifest.
- **Payload URLs come from the signed manifest, never from the offer.** This is
  what closes the attack in §1.3: a spoofed or server-side-compromised offer has no
  URL to offer.
- The offer decides *whether to show* an update. It can never decide *what gets
  installed*.
- **Downgrade protection:** the manifest carries a monotonic `serial`. The daemon
  refuses any manifest whose serial is ≤ the last successfully installed serial,
  recorded in `/var/lib/otaready/last-serial`. Prefer this to an `expires`
  timestamp — the TouchPad's clock is unreliable across battery pulls.
- **Target binding (image-side §12.1) — a second local interlock.** `serial` stops a
  *downgrade* but not a *lateral swap*: a compromised server, or anyone who controls
  which manifest URL the offer names, can serve a **validly signed** manifest meant
  for a different model, baseline or OS version with a higher serial, and every
  signature check passes. So the manifest must carry its intended target — model plus
  an OS-version range — and **the daemon refuses a mismatch locally and
  unconditionally**, with the same standing as M3's kernel interlock. Without this,
  "signed" means "signed by us for *something*", not "intended for this device".
- **Rotation (answers §1.4):** a signed manifest may carry a `keyring` block
  introducing the next public key, signed by the current key. The daemon writes
  accepted keys to `/var/lib/otaready/keys/` and will verify against the baked key
  **or** any key transitively introduced from it. The baked key remains the root
  and is never removed, so rotation never requires a re-flash.

Net security property: a compromised server or a MITM with a valid TLS cert can
suppress updates or display a bogus banner, but **cannot cause any code to be
installed**. The signing key stays offline, and M2's dynamic eligibility is
preserved.

### Signature format — SETTLED, verified on hardware 2026-08-30

Detached `openssl dgst -sha256 -sign`, base64, as `<name>.sig` beside each
artefact — as the image side suggested. **Algorithm: RSA-4096, SHA-256, PKCS#1 v1.5.**

Keypair generated; public half committed at `keys/ce-ota-signing.pub`, fingerprint
in `keys/ce-ota-signing.pub.sha256`:

```
3f:02:d3:69:e6:9d:86:e3:61:6f:85:f0:4b:42:db:6d:c7:38:38:17:fc:48:07:89:87:72:16:f2:e3:f9:fa:79
```

**Correction to the image side's §1:** the verifier does **not** need the
`/usr/lib/ssl11` stack. Tested on TestpadE against the **stock `/usr/bin/openssl`,
which is OpenSSL 0.9.8k (2009)** — the same binary 3.0.5 ships:

| Case | Result |
|------|--------|
| Valid RSA-4096 / SHA-256 detached signature | `Verified OK`, exit 0 |
| Tampered payload, good sig + key | `Verification Failure`, exit 1 |
| Good payload, wrong key | `Verification Failure`, exit 1 |
| Missing signature file | error, exit 1 |
| base64 decode (`enc -d -base64` and `base64 -d`) | both work |

So `ce-ota-verify` is a ~40-line shell wrapper over the stock binary, adding no
dependency and working **identically on 3.0.5 and 3.1.0**. This matters more than it
first appears: a device that has not yet modernised its crypto can still verify an
update, so the trust anchor does not depend on the thing it might be delivering.

### Consequence: the transport need not be trusted

Because integrity comes from the offline signature rather than TLS, a signed
manifest and payload can be served over **plain HTTP** to devices that cannot do
modern TLS at all — i.e. every `T=0` baseline (C, D, G, H). Today those devices are
refused with `INSTALL_TLS` because they cannot reach an HTTPS server, which forces a
manual Preware step before they can be bootstrapped.

**This is worth the image side's attention:** it potentially removes the manual TLS
prerequisite from the 3.0.5 bootstrap path entirely. It does not weaken anything —
a plain-HTTP attacker can suppress or corrupt a download, but cannot forge a
signature, and a corrupted download fails its `sha256` check. Confidentiality is not
a property we need for the **payload** — nothing in it is secret.

**Caveat (image side): the payload is not the only thing on the wire.** The offer
*request* carries the device fingerprint — os version, model, kernel state, installed
patch evidence. Over plain HTTP that is a cleartext device inventory for anyone on
the path, and unlike the payload it is not covered by any signature. So the
"transport need not be trusted" conclusion applies to fetching **signed manifests and
payloads**, not to the offer exchange.

Recommended split:

- **Offer request/response: HTTPS wherever the device can.** Every 3.1.0 device can —
  it ships curl 7.88.1 + OpenSSL 1.1.1w. Only `T=0` baselines on 3.0.5 need the
  fallback.
- **Manifest and payload: plain HTTP is fine**, for exactly the reason above.
- **Minimise identifying fields** in the facts sent over a plain-HTTP fallback. Send
  what eligibility genuinely needs; a device serial or nduid on the wire in the clear
  is worth avoiding when the alternative costs nothing.

**RESOLVED — the image side agrees the two-tier split**, and withdrew its earlier
request to sign the offer directly: signing a dynamic per-device response would put
the private key on an internet-facing host, which the trust model forbids. Offline-
signed manifest carrying the URLs, TLS-only offer that decides only whether to *show*
an update, is the correct decomposition.

---

---

# Part III — What the image bakes

## Source inventory (build host)

Verify these md5s before packaging.

| ID | Absolute source path | Bytes | md5 |
|----|----------------------|-------|-----|
| F1 | `.../otaready-app/org.webosarchive.otaready/device/otaready-daemon` | 13400 | `f9d3e5b767b46944bc6f865312e67749` |
| F2 | `.../otaready-app/org.webosarchive.otaready/device/otaready-daemon.conf` | 252 | `0d30cae4e8b8825fc6b95fa639274ec8` |
| F3 | `.../otaready-app/org.webosarchive.otaready/device/UpdatesApp.patched.js` | 27166 | `838830c833ff675b86c9caef2a49d4e2` |
| F4 | `.../webos-update-server/device-scripts/direct-update.sh` | 6987 | `e7c8c4641b4bfe5c5a410236be9e2115` |
| F5 | `.../webos-update-server/device-scripts/fingerprint.sh` | 12747 | `500728fe294d100ad7971fddc3220f63` |
| F6 | `.../otaready-app/org.webosarchive.otaready.service/index.js` | 922 | `1658e292dae071ab4de3d21c61c8bb2c` |
| F7 | `.../otaready-app/org.webosarchive.otaready.service/commands/Trigger.js` | 1380 | `d68c397845db034eb90654c4561f1f87` |
| F8 | `.../otaready-app/org.webosarchive.otaready.service/services.json` | 568 | `f3788abe3826ab69f9276f9a94a841f2` |
| F9 | `.../otaready-app/org.webosarchive.otaready.service/sources.json` | 115 | `f587e573cb101a82d849bed1b94fa6c1` |
| F10 | `.../otaready-app/org.webosarchive.otaready.service/palm_bus_config.json` | 82 | `9b21e57c8f2a26586d3e703729378332` |
| F11 | `.../otaready-app/org.webosarchive.otaready.service/ls2/role.prv.json` | 237 | `4fc3c2182416d973d487e688c901f888` |
| F12 | `.../otaready-app/org.webosarchive.otaready.service/ls2/role.pub.json` | 237 | `4fc3c2182416d973d487e688c901f888` |
| F13 | `.../otaready-app/org.webosarchive.otaready.service/ls2/org.webosarchive.otaready.service.service` | 160 | `0f7e68d663fa84088d6a9be352d31b1b` |
| F14 | `.../keys/ce-ota-signing.pub` — CE OTA signing public key (RSA-4096 PEM) | 800 | fingerprint in `keys/ce-ota-signing.pub.sha256` |
| F15 | `.../webos-update-server/device-scripts/ce-ota-verify` | — | shell wrapper over stock `/usr/bin/openssl` |

Path prefix for F1–F13 is `/home/jonwise/Projects/webos-update-exploration`.

Reference only, not shipped:

- `.../otaready-app/control/postinst` — the 3.0.5 app installer; reference for what
  goes where.
- `.../otaready-app/reference/com.palm.app.updates/UpdatesApp.js`
  (md5 `970404915fed1896bd23a49008ee2840`) — the stock file F3 replaces. Confirmed
  byte-identical to the stock file in the RC.

`F5` is byte-identical to `otaready-app/.../device/ota-fingerprint`. The 3.0.5 app
kept two copies in sync; the image ships one. **Use the `webos-update-server/device-scripts/`
copy as canonical.**

---

---

## Target layout (device rootfs)

| Source | Target path | Mode |
|--------|-------------|------|
| F1 | `/usr/bin/otaready-daemon` | 755 |
| F2 | `/etc/event.d/otaready-daemon` | 644 |
| F3 | `/usr/palm/applications/com.palm.app.updates/app/UpdatesApp.js` | 644 |
| F4 | `/usr/bin/ota-direct-update` | 755 |
| F5 | `/usr/bin/ota-fingerprint` | 755 |
| F6–F10 | `/usr/palm/services/org.webosarchive.otaready.service/` (preserve `commands/`) | 644 files, 755 dirs |
| F11 | `/usr/share/ls2/roles/prv/org.webosarchive.otaready.service.json` | 644 |
| F12 | `/usr/share/ls2/roles/pub/org.webosarchive.otaready.service.json` | 644 |
| F13 | `/usr/share/dbus-1/system-services/org.webosarchive.otaready.service.service` | 644 |
| F13 | `/usr/share/dbus-1/services/org.webosarchive.otaready.service.service` | 644 |
| F14 | `/usr/share/ce-ota/keys/ce-ota-signing.pub` | 644 |
| F15 | `/usr/bin/ce-ota-verify` | 755 |

All root:root.

**Changed in rev 2 (image-side §5).** Registration moved off `/var/palm/ls2/...`
(the app-install convention, on the separate `store-var` volume) to the image
convention above, which is proven on hardware for USB Settings, Backup and the
Synergy transport. Two traps, both load-bearing:

- The launcher filename **must** end in `.service` or D-Bus ignores it silently.
  Since the service id already ends in `.service`, the correct filename is the
  doubled `org.webosarchive.otaready.service.service`.
- The private and public hubs read **different** directories, so F13 is written
  twice.

**Removed in rev 2 (image-side §4).** The row creating `/media/internal/.otaready/`
is gone — it was not implementable. `/media/internal` is `store-media`, a separate
VFAT volume mounted over the rootfs mountpoint, so anything the rootfs tar places
beneath it is shadowed once the volume mounts. The state directory is now created
at runtime; see **M9**.

Stock dependencies confirmed present in the RC — do not remove:
`/usr/bin/run-js-service`, `/usr/share/ota-scripts/{make-update-uimage,ota.sh,pre-update,post-update}`,
`/var/lib/software`, `/var/lib/update`, `/usr/lib/ssl11`.

---

---

## State directory layout

Image-side §4 established that `/media/internal` **survives a Doctor flash**, so a
stale `.installed` would suppress all offers on what the user believes is a fresh
device, and a stale `arm-install` would survive a re-flash. Control and latch state
therefore must live somewhere wiped per flash.

| File | Location | Rationale |
|------|----------|-----------|
| `.installed`, `last-serial`, `server-state.json`, `keys/`, daemon log | `/var/lib/otaready/` | must reset per flash |
| `arm-install` | `/var/lib/otaready/` | must never survive a re-flash |
| `cmd` (bridge → daemon) | `/var/lib/otaready/` if the bridge can write there, else `/media/internal/.otaready/` | see below |
| `offer.json`, `status.json`, `install-status.json` | wherever the patched UI can read them | **OPEN — see §9.2** |

**The per-flash wipe assumption is CONFIRMED (2026-08-30).** The image side's claim
that `/var` resets per flash was verified on TestpadE: `/var/lost+found` is dated
`Aug 29 19:18`, inside the 3.1.0 flash window, and `lost+found` is created by
`mkfs` — so `store-var` was reformatted during the flash. `/var` is its own ext3
volume (`/dev/mapper/store-var`), separate from both `store-media` (vfat,
`/media/internal`) and `store-log` (`/var/log`). Control state placed under
`/var/lib/otaready/` therefore genuinely does not survive a re-flash.

*Incidental:* `/var/log` being a separate volume means the daemon log, if moved to
`/var/lib/otaready/`, lands on `store-var` rather than the cramped 23 MB
`store-log` — which partly addresses image-side §6 by relocation. The size cap is
still wanted. Also noted: the rootfs is mounted **read-only**; M4 removes the only
code that needed it writable.

**RESOLVED on hardware 2026-08-30 — no app-level probe needed.** The answer came
from the jailer configuration rather than an experiment, and it is decisive.

`/usr/bin/run-js-service` classifies our service (`org.webosarchive.otaready.service`
is not `com.palm.*`) into the third-party branch, where `thirdparty_jail=individual`
keeps the jail **on**. Baking it into ROM changes only the jail *type*
(`triton` instead of `triton-inst`), not whether it is jailed. Both
`/etc/jail_triton.conf` and `/etc/jail_triton-inst.conf` were read on device, and
for our purposes they are identical:

- `mount rw /media/internal` — **writable**
- also rw: `/tmp`, `/proc`, `/dev/shm`, `/var/run`, `/var/file-cache`, `/var/palm/tokens`
- `/var/luna/preferences` ro
- **`/var/lib` is never mounted at all** — it does not exist inside the jail

So the bridge service **cannot** write `/var/lib/otaready`, under either jail type.
That is precisely why `Trigger.js` uses `/media/internal`.

**Resolution — split by writer, not by file type.** This satisfies the image side's
actual concern (state that must not survive a Doctor flash) without needing the app
to read `/var/lib` at all, so the unresolved WebKit question becomes moot:

| Files | Location | Writer / reader |
|-------|----------|-----------------|
| `.installed`, `last-serial`, `arm-install`, `keys/`, `server-state.json`, daemon log | `/var/lib/otaready/` | **daemon only** (root, unjailed). Never read by the app or the bridge. Wiped per flash. |
| `offer.json`, `status.json`, `install-status.json` | `/media/internal/.otaready/` | daemon writes, app reads via `file://` |
| `cmd` | `/media/internal/.otaready/` | bridge writes (only path it can), daemon reads |

The two files the image side was most worried about — `arm-install` and
`.installed` — are daemon-only, so they move to `/var/lib/otaready` and are
inherently flash-wiped. **M9's first-boot cleanup is still required** for the two
developer overrides that must live on `/media/internal` where the daemon reads them
(`test-offer.json`, `server-url`).

A useful side effect: this layout is identical on 3.0.5 and 3.1.0, since both jail
types mount the same paths. OTA Ready v2 can use it unchanged.

---

---

## Required modifications

### M1 — bridge service Exec path (F13) — *unchanged, endorsed*

```diff
-Exec=/usr/bin/run-js-service -n /media/cryptofs/apps/usr/palm/services/org.webosarchive.otaready.service
+Exec=/usr/bin/run-js-service -n /usr/palm/services/org.webosarchive.otaready.service
```

### M2 — daemon: server-side eligibility (F1, `make_offer`)

Remove the local verdict gate:

```diff
-    ready_ok=false
-    grep -q '"ready":true' "$STATUS" 2>/dev/null && ready_ok=true
```

and the branch consuming it:

```diff
-    elif [ "$ready_ok" != true ]; then
-        printf '{"status":"UpToDate","networkAvailable":true}\n' > "$OFFER"
-        offer_status=UpToDate; src=excluded
```

Replace the fetch (F1 line 90) with a POST carrying the device facts, a **protocol
version** (image-side §2 corollary) and a nonce:

```sh
facts=$(/bin/sh "$FP" --json 2>/dev/null)
nonce=$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
body=$(printf '{"protocol":1,"nonce":"%s","device":%s}' "$nonce" "$facts")
resp=$(curl -s -m 15 -H 'Content-Type: application/json' \
       --data-binary "$body" "$(server_url)/api/updates/offer" 2>/dev/null)
```

Keep the existing `live_ok` / unreachable branch — it already fails closed to
`UpToDate`, which is required.

### M3 — daemon: local kernel interlock (F1) — *endorsed by image side*

Before the server call, refuse locally and unconditionally:

```sh
if ! grep -q '"kernel":"stock"' "$STATUS" 2>/dev/null; then
    printf '{"status":"UpToDate","networkAvailable":true}\n' > "$OFFER"
    offer_status=UpToDate; src=kernel-interlock
    return
fi
```

Must run even when the server says "offer". Not server-overridable.

### M4 — daemon: delete the runtime-patch machinery (F1) — *unchanged*

Remove: constants `SU_JS`, `SU_BAK`, `SU_APPINFO`, `SU_APPINFO_BAK`, `PATCHED`
(lines 27–31); functions `apply_patch`, `revert_patch`, `bump_su_version`,
`luna_restart`; the `redirect` and `revert` command cases; `write_server_state`'s
dependence on `[ -f "$SU_BAK" ]`; writes to `redirect-result.json`.

Retain: `refresh_status`, `make_offer`, `do_install`, `mark_installed`, the `check`
/ `install` / `reset` commands, the `.installed` latch.

### M5 — daemon: diagnostics app-version reference (F1)

```diff
-    appver=$(sed -n 's/.*"version"[ ]*:[ ]*"\([0-9.]*\)".*/\1/p' "$APP_APPINFO" 2>/dev/null | head -1)
+    appver=$(grep '^PRODUCT_VERSION_STRING=' /etc/palm-build-info 2>/dev/null | cut -d= -f2)
```

Remove the `APP_APPINFO` constant. Keep `write_diagnostics`. Its `df -k`
NF-relative parse is correct — do not "simplify" it back to positional columns.

### M6 — direct-update: send a real version (F4, `get_current_build`, lines 16–19)

```diff
-        BUILD=$(grep "^BUILDNAME=" /etc/palm-build-info | cut -d= -f2)
+        BUILD=$(grep "^PRODUCT_VERSION_STRING=" /etc/palm-build-info | cut -d= -f2)
```

`Nova-HP-Topaz` parses to `(0,0,0,0)`, making `target_build` gating inert. 3.1.0
yields `webOS CE 3.1.0` → `(3,1,0,0)`.

### M7 — fingerprint: facts, not verdict (F5) — *endorsed, and stronger than stated*

The image side reports the launcher binary changed **twice this week**
(`4596905` → `4598095` bytes) and that the image byte-patches its version string on
top of whatever LunaCE produces. Any hash-pinned gate is a fleet-wide outage waiting
for a rebuild.

- Delete `FP_MD5_STOCK`, `FP_MD5_CE_RELEASE`, `FP_MD5_CE_CUSTOM` and the
  `case "$FP_LUNA_MD5"` block. **Do not add 3.1.0's hash.**
- Report launcher identity from the embedded string:
  `strings /usr/bin/LunaSysMgr | grep -m1 'WebOS Ports LunaCE'`. Report, do not gate.
- Delete the A–H classification and the `UNKNOWN`/`REVIEW` verdict.
- Keep Gate 1 (model) and Gate 2 (custom kernel), both reported; Gate 2 drives M3.
- `--json` must keep emitting `"kernel":"stock"` verbatim, since M3 greps for it.
  Add `"os_version"` from `PRODUCT_VERSION_STRING`.

### M8 — bridge service: trim commands (F7, F8, F9) — *unchanged*

`Trigger.js`: reduce `ALLOWED` to `{ check: 1, install: 1, reset: 1 }`.
`services.json`: remove the `saveDetails` entry. `sources.json`: remove
`commands/SaveDetails.js`. Do not ship `SaveDetails.js`.

### M9 — NEW: create the state directory at runtime (image-side §4)

The image cannot create it (§3). The daemon must `mkdir -p` its state directory at
startup, before first use. F1 already does `mkdir -p "$DIR"` near the end of the
file — **move it above first use** and add the second directory.

If UI-read files must stay on `/media/internal` (§9.2), the daemon must also
**actively delete stale control files at boot** when `/var/lib/otaready` is absent,
which indicates a first boot after a flash:

```sh
if [ ! -d /var/lib/otaready ]; then
    rm -f /media/internal/.otaready/arm-install \
          /media/internal/.otaready/test-offer.json \
          /media/internal/.otaready/server-url \
          /media/internal/.otaready/.installed
fi
mkdir -p /var/lib/otaready /media/internal/.otaready
```

`arm-install` is the critical one — it arms an irreversible flash.

### M10 — NEW: signature verification (image-side §1)

- Fetch the manifest and its `.sig`; call `ce-ota-verify` against
  `/usr/share/ce-ota/keys/ce-ota-signing.pub` before parsing.
- Verify each downloaded package's `sha256` against the signed manifest before
  handing anything to `ota-direct-update`.
- Refuse any manifest whose `serial` is ≤ `/var/lib/otaready/last-serial`.
- **Signature failure ⇒ refuse, log once, and do not retry in a loop** (image-side
  §6). Back off to the daily floor; do not treat it as a transient network error.
- Nothing under `/boot` is touched and no package is installed on any failure.

**Verify-then-install is a TOCTOU — stage first (image-side §12.2).**
`ce-ota-verify` validates a file *by path*, and whatever installs it re-opens that
path. Any gap between the two is exploitable if the file lives somewhere writable,
and **`/media/internal` is exported to the host as USB mass storage** — a user in
drive mode, or anything else with write access to that volume, can swap a payload
between the check and the install. Therefore:

1. Download to `/media/internal` if you must, but **move the payload into
   root-only storage (`/var/lib/otaready/`) BEFORE verifying it.**
2. Verify there.
3. **Re-check the manifest's `sha256` at install time** as the authoritative gate.

Never verify a file in place on `/media/internal` and then install from that path.

### M11 — NEW: forward-compatible parsing (image-side §2)

Audited in F3 on 2026-08-30:

- **Unknown fields** are already tolerated — the payload is passed through as an
  object and read by key. No change needed.
- **Parse failure** already fails closed (F3 line 184 catches and substitutes
  `{status:"UpToDate"}`). Keep.
- **Unknown `status` does NOT currently degrade correctly.** The chain has a
  terminal `else` at line 398 that only hides the download pill, then passes the
  payload to the stock `UpdateStatus` / `UpdateHeader` sub-kinds, which render
  ambiguous or stale text. **Required fix — normalise at ingest**, in the offer XHR
  handler, before `setPayload`:

  ```js
  // Explicit comparison, NOT a lookup object. See the warning below.
  if (p.status !== "Available" && p.status !== "UpToDate") {
      p = {status:"UpToDate", networkAvailable:true};
  }
  ```

  **⚠️ Do not write this as `if (!KNOWN[p.status])` over an object literal.** That
  was the original form of this fix and it is wrong (caught by image-side §12.3):
  a bare object inherits from `Object.prototype`, so `KNOWN["constructor"]`,
  `"toString"`, `"valueOf"`, `"__proto__"` and `"hasOwnProperty"` are all truthy and
  pass as *known* — failing **open** in the one piece of code whose entire job is to
  fail closed. Verified: five of eight test statuses were misclassified. If the list
  ever grows enough to want a lookup, use
  `Object.prototype.hasOwnProperty.call(KNOWN, p.status)`.

  This is the minimal change that satisfies image-side §2.2 and VS6.
- **Display strings must be pass-through.** F3 already passes `version`, `size` and
  `installTime` through. Any future field must follow the same rule.
- **Unrelated defect found during the audit:** F3 still ships
  `{kind:"HelpMenu", target:"http://help.palm.com/updates/index.html"}` — a dead
  Palm URL. Repoint or remove before baking, since it is frozen once shipped.

### M12 — NEW: bounded polling and logging (image-side §6)

- `REFRESH_EVERY` is currently **15 seconds, forever**. Replace with exponential
  backoff to a **daily floor**. A dead or slow server must not be hammered.
- **No polling before first-use completes.** F2 starts the daemon on
  `started LunaSysMgr`, which is early in an already-crowded first-boot window.
  Gate the first poll on first-use completion.
- `/var/log` is a 23 MB volume. Cap the daemon's own log by size and do not log
  per-poll noise. F1's existing `_last_offer` guard (log only on offer change) is
  the right instinct — extend it to a size cap with truncation.

### M14 — NEW: the baked server URL

The update server address is a **bootstrap value**, in the same category as the
signing key (§0): a device cannot discover the server without already knowing where
to look, so it has to be in the image. Name it as an explicit exception to
"bake mechanism, never policy" rather than letting it slip in unnoticed.

**Defect to fix before baking.** The URL is specified in two places and they
disagree:

| Location | Value | |
|---|---|---|
| `otaready-daemon:23` | `SERVER_DEFAULT="https://swupdate.webosarchive.org"` | correct |
| `direct-update.sh:8` (**both copies**) | `SERVER_URL="${1:-http://192.168.10.20:8080}"` | **dead LAN IP** |

The daemon always passes the real URL as `$1`, so the fallback is dormant — but F4
is on the bake list, and this is a recurrence of the exact bug already fixed once in
the daemon (see `otaready-app/CLAUDE.md` lesson #13). Change the fallback to the
production hostname, or make a missing `$1` a hard error.

**Requirements:**

- **Bake a hostname, never an IP.** DNS is the indirection layer that lets the
  server move without touching devices.
- **Keep the `server-url` override file** for LAN development.
- **Make the URL relocatable by signed manifest** — a signed update should be able
  to carry a new server address, exactly as it carries a rotated key (§1). Without
  this, a server migration means re-flashing the fleet.
- **Consider a baked fallback list** (primary + secondary hostname) as cheap
  insurance against one name failing.

**Operational consequence — needs an owner, not just a decision.**
`webosarchive.org` becomes critical infrastructure the moment 3.1.0 ships, with the
same cannot-be-fixed-later property as the signing key. If it lapses or changes
hands, every baked device is permanently stranded with no recovery short of a
re-flash. Treat it accordingly: documented ownership, long registration, renewal
alarms, and ideally not a single point of control.

### M13 — NEW: safe self-replacement (image-side §3)

The daemon is a `/bin/sh` script, and **overwriting a running shell script in place
corrupts its execution** — `sh` re-reads from a byte offset, so a `cp` over a live
`otaready-daemon` will make it execute garbage partway through an update. This is a
concrete failure mode for image-side §3's requirement that the client be replaceable
by the payload it installs.

Requirements on the payload format and `post-update`:

- Install a new daemon to a temporary path on the **same filesystem** and `mv` it
  into place. `mv` within a filesystem is `rename(2)`: the running process keeps the
  old inode open and finishes cleanly, while the new file takes the name. **Never
  `cp` over the running daemon.**
- `post-update` must restart the daemon rather than assume a reboot has done it.
- The daemon must not hold its own files open across the update.

---

---

## Do not include in the image

- The Enyo app `org.webosarchive.otaready` in any form.
- `source/Updater-Helper.js`, `commands/SaveDetails.js`.
- Any `/media/cryptofs/apps/...` OTA payload.
- Any control or latch file: `arm-install`, `test-offer.json`, `server-url`,
  `.installed` — in **either** state directory.
- Any `*.otaready-orig` backups under `/usr/palm/applications/com.palm.app.updates/`.

The image ships the client **disarmed** (image-side §6), and the build verifies it.

---

---

# Part IV — Contracts the frozen client must honour

## Forward compatibility, or the server is frozen too

Server-side freedom is only real if the frozen client tolerates a server that has
moved on. Three rules, all of which the daemon and the patched UI must obey:

1. **Unknown fields are ignored, never fatal.** The server will add fields we
   have not thought of. A strict parser turns an additive server change into a
   fleet-wide breakage.
2. **Unknown `status` values mean "no update".** Fail closed on anything not
   understood. Today's set is `UpToDate` / an offer; tomorrow's might include
   `Deferred`, `Blocked`, `Retry`. An old device must degrade to doing nothing,
   not to doing something wrong.
3. **Display strings come from the server, not the device.** Title, description,
   size, install time, release notes — all pass-through. Anything the device
   composes itself is a string we can never change.

Corollary: the request must carry a **protocol version** (`"protocol": 1`) so the
server can branch on client vintage forever. Add it to the M2 POST body.

---

---

## Self-replacement: the client must be replaceable by its own payload

This is the escape hatch that makes every other mistake survivable. The first
successful OTA must be able to replace `/usr/bin/otaready-daemon`, the
`ota-scripts`, `ce-ota-verify`, and `UpdatesApp.js` themselves.

Requirements this places on the payload format:

- A payload may rewrite the updater. The daemon must not hold its own files open
  in a way that breaks mid-update, and must tolerate being replaced and restarted.
- `post-update` must be able to restart the daemon rather than assuming a reboot
  has done it.
- Please add a self-update smoke test to the server-side test matrix: an update
  whose only content is a new `otaready-daemon`.

If this works, "we baked the wrong thing in 3.1.0" costs one OTA rather than a
re-flash of every device.

---

---

## Dormant, fail-closed, and bounded by default

The image ships the client **disarmed**, and we will verify that in the build:

- No `arm-install`, no `test-offer.json`, no `server-url`, no `.installed`.
- Unreachable or silent server ⇒ `UpToDate`. (§M2 already does this; keep it.)
- The kernel interlock (M3) stays local and non-overridable. Agreed and endorsed:
  it is a safety interlock, not policy.
- **Add: signature failure ⇒ refuse, loudly, and do not retry in a loop.**

Two operational limits we want on device, because we cannot change them later:

- **Bounded polling.** A dead or slow server must not be hammered. Exponential
  backoff to a daily floor, and no polling at all before first-use completes —
  the first-boot window on this image is already crowded enough that we have
  spent this week fixing races in it.
- **Bounded logging.** `/var/log` is a 23 MB volume and `messages` rotates fast
  enough that we have twice lost the evidence for a crash. The daemon's own log
  must be size-capped and must not log per-poll noise at notice level.

---

---

## Server-side counterpart (out of scope for the image; sequencing critical)

- `/api/updates/offer` must accept the M2 POST body (with `protocol` and `nonce`)
  and return the offer or `{"status":"UpToDate"}`.
  `webos-update-server/dm/eligibility.py` holds the policy logic.
- The signed manifest of §1 must be produced and published.
- **Deploy both before any image ships with M2**, or every device receives the
  unconditional offer.
- Add a **self-update smoke test** (image-side §3): an update whose only content is
  a new `otaready-daemon`, exercising M13's rename path.

---

---

# Part V — Validation

Device commands go over novacom; multi-word commands must be piped through
`novaterm`, not `novacom -- run /bin/sh -c` (which re-tokenizes on spaces). See
`video-crash/_lib.sh`.

### Static — placement

- **V1** All §3 targets exist with the specified modes.
- **V2** `md5sum /usr/palm/applications/com.palm.app.updates/app/UpdatesApp.js`
  → `838830c833ff675b86c9caef2a49d4e2`. If it returns
  `970404915fed1896bd23a49008ee2840`, the stock file shipped and the reroute is absent.
- **V3** No `*.otaready-orig` under the System Updates app.
- **V4** *(revised)* No control files in **either** state directory. Explicitly
  confirm `arm-install` is absent. Do **not** assert the image created
  `/media/internal/.otaready` — it cannot.
- **V5** The two D-Bus launcher files exist, both named `...service.service`, and
  their `Exec=` points at `/usr/palm/services/...` (M1 applied).
- **V6** `/usr/share/ce-ota/keys/ce-ota-signing.pub` and `/usr/bin/ce-ota-verify`
  exist; the key's fingerprint matches the published one.

### Runtime — daemon

- **V7** `initctl list | grep otaready` → `start/running`.
- **V8** `status.json` and `offer.json` appear within one poll interval; check
  `/var/log/otaready-daemon.log`.
- **V9** `/bin/sh /usr/bin/ota-fingerprint --json` returns valid JSON containing
  `"kernel":"stock"` and `os_version` `webOS CE 3.1.0`, and **no** `verdict` field.

### Runtime — bridge (key regression test)

- **V10** On the **first boot, with no reboot performed**:
  ```
  luna-send -n 1 -f palm://org.webosarchive.otaready.service/trigger '{"cmd":"check"}'
  ```
  → `{"returnValue":true,"queued":"check"}`. This is the whole reason for baking.
  A service-not-found error means the §3 registration files are missing or misnamed
  (check the doubled `.service` suffix). Allow 1–2s for node cold-start.

### Runtime — end to end

- **V11** `curl -s -m 20 https://swupdate.webosarchive.org/api/updates/offer` from
  the device → 200 + JSON. (Confirmed on the RC: curl 7.88.1, OpenSSL 1.1.1w.)
- **V12** System Updates → Check Now renders the server's offer with a non-empty
  install time. No contact with any Palm/HP host.
- **V13** Server logs `Direct update check for build: webOS CE 3.1.0`, not
  `Nova-HP-Topaz` (M6 applied).

### Safety

- **V14 — install stops unarmed.** With `arm-install` absent, trigger
  `{"cmd":"install"}`. Expect `install-status.json` to reach
  `{"status":"prepared","note":"not armed..."}` and **no reboot**. Any reboot is a
  release blocker.
- **V15 — kernel interlock.** Verify on the build host, not hardware: run the M7
  fingerprint against a fixture where `/boot/uImage` points at a non-stock target,
  confirm a non-`stock` kernel is reported, and confirm M3 writes `UpToDate`
  regardless of the server response. Do not install a community kernel on a test
  device.
- **V16 — fail closed.** With networking disabled, `offer.json` → `UpToDate`.

### Signing and forward-compatibility (image-side §8)

- **VS1** `ce-ota-verify` accepts a correctly signed fixture and **rejects** a
  tampered payload, a good payload with the wrong key, and a missing signature.
- **VS2** With a valid offer but a **bad signature**, nothing is installed and
  nothing under `/boot` is touched.
- **VS3** The state directory is created at runtime on a device that never had it.
- **VS4** A freshly flashed device does not inherit `.installed` or `arm-install`
  from the pre-flash `/media/internal`.
- **VS5** The bridge answers on **first boot with no reboot** (same as V10).
- **VS6** Unknown `status` values and unknown extra fields degrade to "no update"
  (exercises M11's normalisation).
- **VS7** *(added)* Replaying a manifest with a `serial` ≤ `last-serial` is refused
  (downgrade protection, §1).
- **VS9** *(added)* A **validly signed** manifest whose declared target is a
  different model or OS version is **refused**, even with a higher `serial`
  (target-binding interlock, §1 / image-side §12.1).
- **VS10** *(added)* A payload staged on `/media/internal` and then swapped after
  verification but before install is caught by the install-time `sha256` re-check
  (TOCTOU, M10 / image-side §12.2).
- **VS11** *(added)* Offer statuses `constructor`, `toString`, `valueOf` and
  `__proto__` all degrade to "no update" (M11 prototype hazard, image-side §12.3).
- **VS8** *(added)* A payload whose only content is a new `otaready-daemon` installs
  cleanly and the daemon restarts — exercising M13's rename path. Confirm the old
  daemon did not execute corrupted script text mid-update.

---

---

## Stock 3.0.5 cross-check — complete, all checks passed

Run 2026-08-30 against a genuinely stock device: `HP webOS 3.0.5`, BUILDNUMBER 86,
BUILDTIME `20111221110520` (the original 2011 HP build), hostname still the default
`webos-device`.

**S1 — stock OpenSSL.** `OpenSSL 0.9.8k 25 Mar 2009`,
md5 `e8d46abf73c188947fc90af177517a77`.

**S1b — the device is genuinely stock.** This is what makes the rest meaningful:

| Check | Result |
|-------|--------|
| `org.webosinternals.*` packages | **none** |
| `curl` | `7.21.7 … OpenSSL/0.9.8k` — the 2011 original, not the suite's 7.88.1 |
| `/usr/lib/ssl11` | absent |
| `/usr/lib/libssl.so.0.9.8` | dated Dec 21 2011 |

**S2 — `ce-ota-verify`, all five cases, on 2009 crypto only.**

| # | Case | Result |
|---|------|--------|
| 1 | valid base64 signature | exit 0 ✅ |
| 2 | valid raw DER signature | exit 0 ✅ |
| 3 | tampered payload | REFUSED, exit 1 ✅ |
| 4 | wrong key | REFUSED, exit 1 ✅ |
| 5 | missing signature | REFUSED, exit 1 ✅ |

**S3 — installed-service jail identical to 3.1.0.** `mount rw /media/internal`;
**no `/var/lib` mount**. The §4 state layout holds unchanged on 3.0.5.

**S4 — `run-js-service` identical to 3.1.0.** Same `jail=on`, `palm_jail=off`,
`thirdparty_jail=individual`; same `/usr/palm/services/*` → `/usr/share/ls2` and
`/media/cryptofs/apps/*` → `/var/palm/ls2` branches. M1 and the jail reasoning
transfer verbatim.

### Conclusion

**The signing scheme is confirmed to work on a device carrying nothing but 2009-era
crypto.** No dependency on the community TLS suite, and no dependency on the thing
an OTA might be delivering. §1 is safe to freeze on this point, and one verifier
plus one signing scheme covers both 3.0.5 and 3.1.0.

*Not compared:* the 3.1.0 device's `/usr/bin/openssl` md5 was never recorded, so the
two binaries were not checked byte-for-byte — only that both report `0.9.8k` and both
verify correctly. Cheap to close if anyone wants it.

---

---

# Part VI — Runbook: shipping an actual OTA

## Eligibility on 3.1.0

Because you built the image, you know its configuration. What still has to be checked
at runtime is only what the *user* can change afterwards. In practice that is one
thing:

**The custom-kernel interlock.** ⛔ This must never be skipped. The OTA rewrites
`/boot/uImage`, and `post-update` restores the stock kernel afterwards. A user who
installs UberKernel or similar after flashing 3.1.0 would have that silently
destroyed. The check stays **on the device** and is **not overridable by the server** —
it is a safety interlock, not a policy, so it has to hold even if the server is
wrong, compromised, or replaying a stale response.

Everything else — who gets an update, when, staged rollouts, holding a release back —
lives on the server and is a `git push`.

**Do not gate on the launcher's checksum.** The LunaSysMgr binary changed twice in a
single week during RC, and the image byte-patches its version string on top of
whatever LunaCE produces. Any checksum-pinned gate is a fleet-wide outage waiting for
the next rebuild.

---

---

## Per-release: building, signing, publishing

Identical to 3.0.5 — see `OTA-3.0.5.md`. Same server, same signing key, same
`offer.json` kill switch, same `serial` bump for downgrade protection.

One 3.1.0-specific note: the device reports its version as `webOS CE 3.1.0`, which
parses to `(3,1,0,0)`. 3.0.5 reports `(3,0,5,0)`. **This is the first time the server
can actually tell the two apart**, which is what makes "offer this only to devices
below 3.1.0" expressible at all. (It requires a one-line client fix — the device
currently sends its product name instead of its version. See
M6, Part III.)

That matters because the natural first real payload is plausibly **3.0.5 → 3.1.0
itself**, which would make several wish-list items — LunaCE, the TLS stack — payload
*contents* rather than separate OTAs.

---

---

## Getting an update onto a device today (Option A)

1. **The owner installs OTA Ready from App Museum II.** ✅ Same as 3.0.5.
2. **One reboot**, for the same `ls-hubd` reason as 3.0.5. ✅
3. **"Use New Update Server"** patches System Updates in place. ✅
   *3.1.0 note:* the CE rootfs is mounted **read-only**, so the patch step must
   `mount -o remount,rw /` first and restore `ro` afterwards. It will also leave
   `UpdatesApp.js` diverging from the image's regenerated ipkg md5sums; harmless at
   runtime, since `integcheck` is a flash-time gate, but it will show up if anyone
   runs it later.

   **⚠️ Checked, and the answer is no — this is a defect in the current app.**
   Verified in `otaready-daemon` on 2026-08-30: `apply_patch` and `revert_patch`
   each begin with `mount -o rw,remount /`, and **neither restores `ro`**. There is
   no `remount,ro` anywhere in the daemon or the postinst — all three sites remount
   rw and leave it that way. The postinst even documents the old assumption in a
   comment: *"root fs is normally rw on the TouchPad"*, which was true on 3.0.5 and
   is **false on CE 3.1.0** (confirmed: `/dev/mapper/store-root on / type ext3 (ro,…)`).

   Consequence: on a 3.1.0 device, the first "Use New Update Server" silently leaves
   the rootfs writable, and nothing ever puts it back. Losing read-only protection
   without telling anyone is exactly the kind of side effect that should not happen
   quietly.

   **Requirement for OTA Ready v2:** record the mount state before remounting and
   restore it afterwards, including on the failure paths. Do not assume the rootfs
   was writable to begin with — on 3.1.0 it is not.
4. System Updates then behaves normally: Check Now → offer → Install. ✅

The difference from 3.0.5 is what the owner *doesn't* have to do: no TLS suite to
install first, no "your configuration isn't recognised" dead end, no browser
prerequisite. Steps 1–3 are the only manual work, and they are one-time.

Under **Option B** this section disappears entirely — the device simply checks for
updates on its own.

---

---

## Verifying it worked

Same commands as `OTA-3.0.5.md`, plus two specific to 3.1.0:

```sh
# the trust anchor is present and is the right key.
# NOTE: `pkey` does NOT exist on the device — stock openssl is 0.9.8k and `pkey`
# arrived in 1.0.0. Confirmed on hardware: it returns "'pkey' is an invalid
# command". Use `rsa -pubin`, which produces an identical fingerprint.
openssl rsa -pubin -in /usr/share/ce-ota/keys/ce-ota-signing.pub \
  -outform DER | openssl dgst -sha256 -c
# must equal keys/ce-ota-signing.pub.sha256

# the verifier works, and correctly REFUSES a tampered file
/usr/bin/ce-ota-verify /tmp/fixture.json /tmp/fixture.json.sig
echo "exit=$?"     # 0 = valid, 1 = refused
```

The verifier's negative cases matter more than the positive one. A verifier that
accepts everything passes a naive test perfectly. Confirm it **rejects** a tampered
payload, a good payload signed with the wrong key, and a missing signature file — all
three were confirmed on hardware on 2026-08-30.

**The safety catch is the same:** the irreversible flash only runs if `arm-install`
exists, and the image ships without it. Exercise the whole chain unarmed first.

---

---

# Part VII — Open items and sequencing

## Open items, in dependency order

**Resolved since revision 1** (both were blocking):

- ~~Signing keypair~~ — **done.** RSA-4096 generated; public half at
  `keys/ce-ota-signing.pub`, fingerprint in `keys/ce-ota-signing.pub.sha256`.
  Private half held off-repo on the signing host. Compatible with stock
  OpenSSL 0.9.8k, verified on hardware (§1).
- ~~The `file://` / state-layout question~~ — **answered from the jailer configs,
  no probe needed.** `/var/lib` is not mounted in either jail type, so the bridge
  cannot write there; layout resolved by splitting on writer rather than file type
  (§4). The WebKit `file://` question is moot under that layout.

**Still open:**

1. **Two-tier trust model (§1) — needs image-side agreement.** Blocks freezing the
   manifest format. Also asks them to consider the plain-HTTP consequence, which
   could remove the manual TLS prerequisite from the 3.0.5 bootstrap.
2. **`ce-ota-verify` review.** Written and tested (`webos-update-server/device-scripts/ce-ota-verify`),
   all five cases pass on device. Needs image-side sign-off before baking, since it
   is a trust component.
3. **Confirm on a *stock* 3.0.5 device.** All crypto testing so far ran on a device
   carrying the community TLS suite. That suite demonstrably replaces binaries
   (`/usr/bin/curl` is 7.88.1, not the 2011 original), so "stock 0.9.8k openssl"
   should be confirmed on a device that has never had those packages — baseline D.
   See §10.
4. **Armed flash is still unverified end to end.** `arm-install` →
   `make-update-uimage` → OTA ramdisk → reboot has never been confirmed on
   hardware. Basis of the image side's §10 sequencing concern.
5. **No real OTA payload exists.** The server hosts test packages and a placeholder
   offer ("webOS Community OTA Test 0.1").

---

---

## Sequencing

The image side proposes two options and prefers **A**:

**A. Bake the trust anchor now, the client when verified.** 3.1.0 ships only
`ce-ota-signing.pub` + `ce-ota-verify` — tiny, inert, impossible to add later. The
client arrives via Preware as it does for 3.0.5. Cost: one manual step before a
3.1.0 device's first OTA.

**B. Bake the whole client, disarmed** — only if V1–V16 and VS1–VS8 all pass on
hardware before release.

**This project concurs with A**, on the image side's own §0 reasoning: the rootfs is
frozen, the armed-flash path is unverified (§9.5), and there is no real payload to
verify it against (§9.6). Freezing an unverified irreversible-flash path into a GA
release is precisely the risk §0 exists to prevent.

Option A also composes well with the planned **OTA Ready v2**. If v2 targets the
same device→server contract on both 3.0.5 and 3.1.0 — facts up, offer down, signed
manifest authorising installs — it becomes a single bootstrapper that simply does
less work on 3.1.0, where the TLS stack and modern curl are already present. 3.1.0
then converges to B in a later release, once the flash path has been proven by
real use on 3.0.5.

Either way the key ships in 3.1.0. That decision does not depend on the rest.

---

# Appendix A — Image-side decision record

Contributed by `webos-doctor-ce`; preserved for attribution and rationale.

## What actually shipped (build 600070)

Everything in §1 is done. The image carries exactly two OTA files:

| Path | Mode | Verified in the shipped rootfs |
|------|------|-------------------------------|
| `/usr/share/ce-ota/keys/ce-ota-signing.pub` | 644 | DER SPKI sha256 `3f02d369e69d86e3…` |
| `/usr/bin/ce-ota-verify` | 755 | default key path points at the baked copy |

`bake.py` computes the key's DER fingerprint at build time and **aborts the build**
on a mismatch. Proven, not asserted: substituting an imposter key produced

```
ERROR: CE OTA signing key fingerprint mismatch
  expected 3f02d369…f9fa79
  got      4c2da7c7…0504d6
  refusing to bake an unexpected trust anchor
```

Build `600070`, `sha256 392f2122e3bd95f6f6b4f89acff2e8038508746a6fdeac7f4c5716834178e65a`,
integcheck clean. Both files are vendored in the image repo at
`build/full-ce/ce-ota/` so a build does not depend on a sibling checkout.

**On M14 (the baked server URL) — the image is clean today.** Every regular file in
the shipped rootfs was scanned for LAN addresses and dev endpoints. The two baked
OTA files contain **no URL or hostname at all**. The `192.168.*` strings that exist
are in stock 2011 binaries we never touch (`PmWiFiService`'s own hotspot default of
`192.168.1.1`, plus `liblunaservice.so` and `node`). `direct-update.sh`'s dead
`http://192.168.10.20:8080` fallback cannot reach a device from the image, because
F4 is not baked under Option A.

**If Option B is ever taken, that stops being true.** Recommendation: make
"hostname, never an IP" a *build-time assertion* over every baked OTA file rather
than a documented rule. The image build already does exactly this for the signing
key, and the same reasoning applies — a dead LAN IP frozen into a GA rootfs is
unfixable by the mechanism it breaks.

M14's operational point deserves repeating in the release checklist rather than a
spec: `webosarchive.org` becomes critical infrastructure the moment 3.1.0 ships,
with the same cannot-be-fixed-later property as the key.

---

---

## Findings from reviewing the spec (all adopted)

The two-tier trust model (§1 of rev 2) is **better than what §1 of this document
asked for, and is adopted**. Signing the per-device offer would have put the private
key on an internet-facing host — violating the rule two paragraphs above it.
Offline-signed manifest carrying the URLs, TLS-only offer that decides only whether
to *show* an update, is the correct decomposition, and the resulting property is the
one that matters: a compromised server can suppress updates or show a bogus banner,
but cannot cause code to be installed.

Four findings follow. **The first three are not yet reflected in the spec.**

### 12.1 The manifest must bind to its target — safety interlock, not policy

`serial` gives downgrade protection: a manifest older than the last installed one is
refused. It does **not** prevent a *lateral* swap. A compromised server (or anyone
who can choose which manifest URL the offer names) can serve a **validly signed**
manifest intended for a different baseline, model, or OS version, with a higher
serial. Every signature check passes.

**Required:** the manifest carries its intended target (model, and an OS-version
range), and the daemon refuses a mismatch **locally and unconditionally** — the same
standing as M3's kernel interlock, for the same reason. Without it, "signed" means
"signed by us for *something*", not "intended for this device".

### 12.2 Verify-then-install is a TOCTOU, and `/media/internal` is USB-exported

`ce-ota-verify` validates a file *by path*; whatever installs it re-opens that path.
Any window between the two is exploitable if the file lives somewhere writable — and
`/media/internal` is exported to the host as USB mass storage. A user in drive mode,
or anything else with write access to that volume, can swap a payload between the
check and the install.

**Required:** move the payload to root-only storage (`/var/lib/otaready/`) **before**
verification, and re-check the manifest's `sha256` at install time as the
authoritative gate. Never verify a file in place on `/media/internal` and then
install from there.

### 12.3 M11's whitelist inherits from `Object.prototype`

```js
var KNOWN = {Available:1, UpToDate:1};
if (!KNOWN[p.status]) { p = {status:"UpToDate", networkAvailable:true}; }
```

`KNOWN["constructor"]` is truthy, as are `"toString"`, `"valueOf"` and
`"__proto__"` — so those statuses pass as *known* in the one piece of code whose
job is to fail closed on unknown statuses. Use an explicit comparison, or
`Object.prototype.hasOwnProperty.call(KNOWN, p.status)`.

Small, but it is in the frozen half under Option B and it defeats the property
VS6 exists to prove.

### 12.4 Rotation state is wiped by a re-flash — *folded into the how-to already*

`/var/lib/otaready/keys/` and `last-serial` do not survive a Doctor flash, so a
re-flashed device falls back to the baked root key and a zero serial. Acceptable —
physical access implies trust — but it means **the baked root must remain a valid
signer forever**, or the keyring chain must stay re-servable from the root. If the
root is ever retired outright, re-flashed devices strand.

---

# Appendix B — Background

## "Why not just ship 3.1.0 pointing at the new update server?"

The obvious question, and the answer is more interesting than "no". The stock
updater is not hardcoded to a dead URL the way the *UI* is:

```
/usr/bin/UpdateDaemon  (stock, 270 KB, present and untouched in 3.1.0)
    FetchServerUrl
    palm://com.palm.accountservices/getServerUrl     <- asks the account service
    omadm.swupdate.palm.com                          <- the default
```

It **asks `com.palm.accountservices` for its server URL at runtime** — and CE already
replaces the account stack. So repointing the stock client is genuinely conceivable
without baking any third-party code. Two things stop it being the easy win:

1. **It speaks OMA-DM, not our API.** `omadm.swupdate.palm.com` is an OMA Device
   Management endpoint. Our server speaks JSON over HTTPS. Repointing means either
   implementing an OMA-DM server, or replacing the daemon — at which point we are
   back to baking a client.

2. **The stock path authenticates nothing.** The only integrity check anywhere in
   `/usr/share/ota-scripts` is `UPDATEFS_MD5`, read from an update-info file that
   travels *with* the payload. That detects corruption, not forgery: whoever serves
   the payload also serves the matching MD5. Pointing that machinery at any server
   creates an **unauthenticated root-level update channel** — precisely what the
   baked signing key exists to prevent.

So "ship it pointing at our server" is really two proposals. Pointing the *UI* at our
server is what OTA Ready's step 3 already does, and baking the patched UI alone
achieves nothing under Option A, because it reads an `offer.json` that only the
(unbaked) daemon writes. Pointing the *stock daemon* at our server needs an OMA-DM
endpoint and would still install unsigned payloads.

The path that actually delivers "no user action" is **Option B** — bake the community
client, with signature verification, once the armed flash is proven. The stock
daemon's `getServerUrl` indirection is worth remembering, though: if a future release
wants the stock UI to show community updates natively, that is the hook.

---

---

## Common misunderstandings

**"3.1.0 is OTA-ready, so there's nothing to do."** Under Option A it ships only the
trust anchor. It is *ready to be made ready* — the client still arrives via Preware.

**"We can add the signing key in the first update."** No. That update would itself be
unauthenticated, which defeats the purpose entirely. The key ships in the image or the
trust model does not exist.

**"TLS protects the download, so signing is optional."** TLS protects the wire.
Signing protects against a compromised or mistaken *server* — and it is what allows
payloads to reach devices that cannot do modern TLS at all.

**"We can fix it later with an OTA."** Only if the OTA mechanism itself works. Anything
baked into the rootfs that breaks the updater cannot be fixed by the updater. That
asymmetry is the reason for every conservative choice in this document.

