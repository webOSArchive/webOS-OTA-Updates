# CLAUDE.md — OTA Ready (CE OTA client) + System Updates

Resume-here notes for this sub-project. Read this first.

## v3.0.0 (2026-11-21): the CE OTA client, webOS CE 3.1.0 onward

OTAs start at CE 3.1.0 (community decision: 3.0.5 -> 3.1.0 is a Doctor flash). v3.0.0
replaced everything 3.0.5-specific (fingerprint, baselines A-H, redirect button,
direct-update.sh, the arm-install switch).

**Proven on hardware 2026-11-21, the way users will do it:** OTA Ready 3.0.0 from App
Museum II -> System Updates opens by itself with the offer -> Install Now -> download from
production -> stock ramdisk -> 600119 -> ce-ota-finish "finished and verified" -> System
Updates opens by itself with "installed" (after ce-ota-finish stops). Two devices
(c37f7a34..., fresh; c68faf11... "C"). The device filter held: C was UpToDate until its
nduid was added to releases.json. A 3.0.5 device shows "Not eligible" correctly.

- **Daemon** `device/otaready-daemon` (root, `/usr/bin`, upstart `start on stopped finish`,
  not tied to Luna). Commands via the bridge: `check | install | cancel | ack`.
  - check: `GET /api/ce-ota/check?build=<BUILDMARK>&nduid=<id>` -> fetch
    `manifests/<name>.json` + `.sig` -> `/usr/bin/ce-ota-verify` with the baked key ->
    `device/ota-manifest.js` (node 0.4, strict, emits shell vars) -> device-side gates:
    HP TouchPad hardware (`/proc/cpuinfo` Hardware TENDERLOIN; a Go is SHORTLOIN, checked
    first so it is refused for that reason), from-buildmark == this build, pre-flight
    md5sums file matches, stock kernel. Then
    `offer.json`. Background check at boot and weekly (wall clock); the first time a
    background check finds a release it opens System Updates (as stock UpdateDaemon did).
  - install: first use done, no ce-* job running, space on /media/internal and on / (the
    manifest's `space`), download to `/media/internal/ce-ota/` (resumable, cancel keeps the
    part), sha256, session files in PmUpdater's format, `PmUpdater -v`, re-hash, arm
    (`updating`, make-update-uimage, check the uImage link), reboot. `STATE/armed` + the
    build after the reboot decide InstallSuccessful/InstallFailed, shown until Done (`ack`).
  - After the update reboot, `announce_result` opens System Updates with
    `updateSuccessful`/`installFailed` (stock create() shows the result), in the background
    once `ce-ota-finish` has stopped.
  - A failed check retries every minute for five tries (the boot check runs before Wi-Fi),
    then every 10 minutes; a good answer resets to weekly.
  - Bench switches in `/media/internal/.otaready/`: `dry-run` (all steps but arming),
    `server-url` (another server; manifests still need the key).
  - busybox sh arithmetic is 32-bit and dies on overflow: all space math is in KB.
- **System Updates** (`device/UpdatesApp.patched.js`): Check Now asks the daemon and waits
  for a newer offer.json; progress 0-40 download, 41-44 checks, 45 restart; SpaceNeeded,
  InsufficientCharge (< 50 %), failure reasons, Cancel, Done -> ack.
- **App** (`source/MainView.js`): status, Device Details incl. **NDUID** (owners send it to
  be added to a rollout), Save/Send Device Details. On 3.0.5 the postinst writes
  "Not eligible" + a docs.webosarchive.org pointer and restores a 1.x-patched System Updates.
- **postinst/prerm**: patch System Updates (backup + appinfo version bump), bridge
  registered live with `ls-control scan-services` (no reboot). prerm restores appinfo only
  on the build it was saved from. **Baking:** an image with `/usr/share/otaready/baked`
  ships its own client; the Museum package then leaves the rootfs alone.
- **Server** (`../webos-update-server/ce_ota.py`): one endpoint; `ce-ota/releases.json`
  sets the blast radius per release (`"devices": "*"` or a list of nduids). Manifests are
  signed with `tools/sign-manifest.py` (key in `../keys/`, never committed); payloads live
  in `[ce_ota] payload_dir` (default `ce-ota/payloads/`, git-ignored, copied by hand), named
  `ce-ota-<from>-<to>.ipk`. The FIRST release in `releases.json` that starts at the device's
  build and admits it wins: list a direct route above a longer one for the same devices.
  `tools/bench-server.py`: stdlib LAN stand-in using the same selection code.
- Payloads come from webos-doctor-ce `build/ota/make-payload.py` (see its Docs/OTA-HANDOFF.md).

## Bench and test

- `tools/bench-server.py` in `../webos-update-server` serves the same release selection on the
  LAN; point a device at it with `/media/internal/.otaready/server-url` and remove the file
  afterwards (it masks production).
- `/media/internal/.otaready/dry-run` runs every install step except arming.

## Hard-won on-device lessons (do not relearn these)

1. **Cache-bust = bump the app version.** Swapping an app's JS and restarting Luna is NOT enough —
   webOS serves cached code. You MUST bump `appinfo.json` `version` to force a reload. Confirmed
   repeatedly (System Updates 1.1.0→1.1.1→1.1.2; Get Ready 1.0.0→1.0.1→1.0.2).
2. **Use plain `XMLHttpRequest` + `JSON.parse`, NOT `enyo.xhr`/`enyo.json`.** This Enyo build's
   `enyo.xhr.request(url, opts)` treats the first arg as an options object (`'sync' in <url>`) and
   throws during `create()` → white screen. Both `UpdatesApp.patched.js` and `MainView.js` use raw XHR.
3. **XHTML 1.1 doctype + first-party markup for theming** — verified (v1.0.3). HTML5
   `<!doctype html>` drops 2011 WebKit into a mode where the era's enyo theme CSS doesn't apply,
   AND the theme only styles real Enyo kinds (`RowGroup`/`Item`/`Toolbar`…), not bare divs.
   Copy `com.palm.app.dateandtime` (index.html doctype, header-welcome/box-center layout) exactly.
4. **Load the system enyo:** `/usr/palm/frameworks/enyo/0.10/framework/enyo.js` (0.10, what the
   themed 1p apps use). The bundled-enyo pattern in `~/Desktop/jonwise/Projects/enyo1-bootplate`
   is only for web/Android portability — not needed (or wanted) here.
5. **Headless launch can't force a fresh `create()`** — webOS restores a "Previously-Saved" card,
   so `luna-send .../launch` over novacom re-shows cached state without re-running the app. **Testing
   the UI requires a human to swipe-close + reopen the app.** (novacomd survives Luna restarts.)
6. **`ipkg -o /media/cryptofs/apps install` DEFERS postinst** — run it manually:
   `sh /media/cryptofs/apps/usr/lib/ipkg/info/<pkg>.postinst`. Real Preware/WOSQI installs run it.
7. **A cryptofs app does NOT shadow a `/usr/palm/applications` system app** of the same id — the
   system app wins. So Part 2 patches the rootfs app in place (backup + version bump), not via a
   cryptofs override.
8. **Enyo apps can't write files** — the Part 2 Install trigger (app→daemon) goes through the
   `org.webosarchive.otaready.service` JS service, which writes `.otaready/cmd`; reads are fine via
   `XMLHttpRequest` to `file://`.
9. **A manually-`ipkg`-installed JS service is NOT registered on the Luna bus** — the real
   installer generates the LS2 role+service files; our postinst does it by hand (copied the
   exact format from the shipping `com.quickoffice.webos.service`: role `exeName:"js"`,
   type `regular`; bus file `Exec=/usr/bin/run-js-service -n <svc-dir>`; both dropped in
   `/var/palm/ls2/{roles,services}/{prv,pub}/`). **ls-hubd caches roles at boot → first install
   needs a reboot** (not just `killall LunaSysMgr`); later app upgrades reuse the same files, no reboot.
10. **On-demand JS services cold-start in ~1-2s** — a foreground `luna-send` can race and look like
   a silent failure (no response printed over novacom either — that's cosmetic). The app-side
   PalmService is async (onSuccess/onFailure) so it waits correctly. To test from a shell, background
   the call and give it a few seconds; confirm via `/var/log/messages` (service `console.log`s land there).
11. **App Museum II (Preware) DOES run our postinst** — VERIFIED on hardware. Installing "OTA Ready"
   from the Museum sets up the daemon + helpers + LS2 files exactly like a manual postinst run. The
   **first-install reboot is only for the bridge service**: State 1 (status display, offer viewing) is
   pure file-reading and works immediately; the first thing that *calls* the service (redirect / install /
   reset / save) fails until one reboot registers it with ls-hubd. One-time; survives upgrades+reboots after.
12. **Ship the PRODUCTION server default.** The daemon's `SERVER_DEFAULT` was a dead LAN IP
   (`192.168.10.20:8080`) for ages; a fresh Museum device couldn't reach anything → stuck State 2 +
   UpToDate. It's now `https://swupdate.webosarchive.org`. A `/media/internal/.otaready/server-url`
   file still overrides it per-device (for LAN dev).

## Build & install

```bash
./build.sh                 # -> org.webosarchive.otaready_<ver>_all.ipk (bump version first!)
# on device (Preware/WOSQI, or for testing:)
#   ipkg -o /media/cryptofs/apps install /media/internal/<ipk>
#   sh /media/cryptofs/apps/usr/lib/ipkg/info/org.webosarchive.otaready.postinst   # run deferred postinst
#   killall LunaSysMgr    # restart to load (app JS)
#   reboot                # ONLY on the FIRST install of the bridge service (ls-hubd role cache; see lesson #9)
```

## Key references
- **Production server:** `https://swupdate.webosarchive.org` (git-to-deploy from `../webos-update-server`;
  `DEPLOY.md` there).
- **App Museum II:** published as **"OTA Ready"** (the self-update check keys off that exact name). The
  Museum installs via Preware, which runs our postinst. Updater lib synced from
  `github.com/webOSArchive/webos-common`.
- 1p apps: `~/Projects/webos-firstparty/` (dateandtime is the Enyo 1 UI template).
- Stock System Updates source: `reference/com.palm.app.updates/` (what we patch).
- The 1.x (3.0.5-era) history of this app is in git before 2026-11-23.
