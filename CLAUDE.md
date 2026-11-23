# CLAUDE.md

CE OTA for HP TouchPads on webOS CE 3.1.0 and later. Start with `README.md` (layout and
the release steps), then:

- `otaready-app/CLAUDE.md`: the client, its daemon, and on-device lessons.
- `OTA-UPDATE-GUIDE.md`: what happens on the device during a flash, and recovery.
- `../webos-doctor-ce/Docs/OTA-HANDOFF.md` and `Docs/OTA-PLAN.md`: payloads, the armed
  flash runbook, every run on hardware. That project builds the payloads.

Rules:

- **Pushing this repo deploys production** (git-to-deploy on `swupdate.webosarchive.org`).
  Ask before pushing. A manifest alone offers nothing; `releases.json` on the host decides.
- The private key (`keys/ce-ota-signing.key`) is never committed.
- Payloads are git-ignored; they go to the host by hand as `ce-ota-<from>-<to>.ipk`.
- Supported routes are 600070 (3.1.0) to the current 3.2.0 build. Beta manifests are
  removed after testing. 3.0.5 is never offered an OTA.
- Server code changes take effect when the host restarts the `webos-update` service;
  `releases.json` and manifests are read per request.

Run the server locally:

```bash
python3 -m venv <venv> && <venv>/bin/pip install -r webos-update-server/requirements.txt
cd webos-update-server && <venv>/bin/uvicorn server:app --host 0.0.0.0 --port 8080
```

The 3.0.5-era OMA DM server, OTA Ready 1.x endpoints and their docs were removed on
2026-11-23; they are in git history.
