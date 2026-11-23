# webOS CE OTA

Over-the-air updates for HP TouchPads running **webOS CE 3.1.0 and later**: the update
server at `swupdate.webosarchive.org`, the OTA Ready client, and the signing key.
3.0.5 → 3.1.0 is a Doctor flash and is never offered over the air.

The payloads themselves are built and proven in the webOS CE Doctor project
(`../webos-doctor-ce`: `build/ota/make-payload.py`, `Docs/OTA-PLAN.md`,
`Docs/OTA-HANDOFF.md`).

## Layout

| Path | What it is |
|------|------------|
| `webos-update-server/` | The production server (FastAPI). `ce_ota.py` is the CE OTA API; `server.py` adds `/health` and `/api/stats`. Deploy notes in `DEPLOY.md` |
| `webos-update-server/ce-ota/` | `manifests/` (signed, tracked), `payloads/` (git-ignored, copied to the host by hand), `releases.json` (who is offered what) |
| `webos-update-server/tools/` | `sign-manifest.py` (sign a payload's manifest), `bench-server.py` (a LAN stand-in with the same release selection) |
| `webos-update-server/device-scripts/ce-ota-verify` | The on-device signature check baked into the CE image |
| `otaready-app/` | OTA Ready 3.x, the client (App Museum II). Read its `CLAUDE.md` first |
| `keys/` | The public signing key, the trust anchor baked into the image. The private key is never committed |
| `OTA-UPDATE-GUIDE.md` | How a flash works on the device: session files, the update ramdisk, recovery from a stuck update |
| `OTA-3.1.0.md` | The September 2026 design for CE OTA (trust model, key, image side) |

## Releasing an update

1. Build and prove the payload in `../webos-doctor-ce` (`make-payload.py build OLD.jar NEW.jar`).
2. Sign it: `webos-update-server/tools/sign-manifest.py <out>/manifest-inputs.json --title "…" --copy-payload`.
   This writes `ce-ota/manifests/<from>-<to>.json` and `.sig` and copies the payload to
   `ce-ota/payloads/ce-ota-<from>-<to>.ipk`.
3. Copy the payload to the host's `ce-ota/payloads/` under that exact name.
4. Commit and push the manifest pair (pushing deploys).
5. Offer it in the host's `ce-ota/releases.json`:

   ```json
   {"releases": [
     {"manifest": "600070-600120", "devices": ["<nduid>", "<nduid>"]},
     {"manifest": "600070-600119", "devices": "*"}
   ]}
   ```

   `"devices"` is `"*"` or a list of nduids. **The first release that starts at the
   device's build and admits the device wins**, so a direct route must be listed above a
   longer one for the same devices. The file is read on every request.

A device reports its nduid in OTA Ready's Device Details. Test against a bench server
first: `tools/bench-server.py --releases <file>`, and on the device
`echo http://<host>:8765 > /media/internal/.otaready/server-url` (remove it afterwards).
