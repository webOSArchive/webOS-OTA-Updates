# OTA Ready

The CE OTA client for HP TouchPads on webOS CE 3.1.0 and later, published in App Museum II
as "OTA Ready". It installs a root daemon and patches the stock System Updates app, so a
release offered by `swupdate.webosarchive.org` appears in System Updates with Install Now.
On webOS 3.0.5 it shows "Not eligible".

- `org.webosarchive.otaready/`: the Enyo app (status, Device Details with the NDUID) and
  `device/` (the daemon, its upstart job, the manifest parser, the patched System Updates).
- `org.webosarchive.otaready.service/`: the JS bridge from the apps to the daemon.
- `control/`: postinst and prerm (run as root; they install the daemon and patch System Updates).
- `reference/com.palm.app.updates/`: the stock System Updates source we patch.
- `build.sh`: builds the ipk. Bump the version in `appinfo.json` first.

Architecture, the install flow and the on-device lessons are in `CLAUDE.md`.
