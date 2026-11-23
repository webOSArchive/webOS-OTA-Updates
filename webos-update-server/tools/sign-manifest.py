#!/usr/bin/env python3
"""Turn a payload's manifest-inputs.json into a signed CE OTA manifest.

    tools/sign-manifest.py ../../webos-doctor-ce/out/ota/600070-600120/manifest-inputs.json \
        [--title "webOS CE 3.2.0"] [--install-minutes 10] [--copy-payload]

Writes ce-ota/manifests/<from>-<to>.json and .json.sig (base64 of an RSA-4096
SHA-256 PKCS#1 v1.5 signature: what /usr/bin/ce-ota-verify on the device checks),
then verifies the pair with the public key before exiting. --copy-payload also
copies the ipk (found next to manifest-inputs.json, sha256 checked) into
ce-ota/payloads/ for a local server; production gets it by hand. On a server the
ipk is named after its route, ce-ota-<from>-<to>.ipk (the manifest's url says so).

Signing needs keys/ce-ota-signing.key (never committed). Writing the manifest
offers nothing to anyone: ce-ota/releases.json decides who sees it.
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
REPO = os.path.dirname(SERVER)
KEY = os.path.join(REPO, "keys", "ce-ota-signing.key")
PUB = os.path.join(REPO, "keys", "ce-ota-signing.pub")
MANIFESTS = os.path.join(SERVER, "ce-ota", "manifests")
PAYLOADS = os.path.join(SERVER, "ce-ota", "payloads")

FORMAT = 1


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs")
    ap.add_argument("--title", help="what System Updates calls it (default: the to-version)")
    ap.add_argument("--install-minutes", type=int, default=10)
    ap.add_argument("--copy-payload", action="store_true")
    a = ap.parse_args()

    with open(a.inputs) as f:
        mi = json.load(f)
    for k in ("from", "to", "payload", "preflight", "tier", "space"):
        if k not in mi:
            sys.exit("manifest-inputs.json has no %r (rebuild the payload with the current make-payload.py)" % k)
    if not os.path.exists(KEY):
        sys.exit("no signing key at %s" % KEY)

    ipk = os.path.join(os.path.dirname(os.path.abspath(a.inputs)), mi["payload"]["file"])
    if os.path.exists(ipk):
        got = sha256_file(ipk)
        if got != mi["payload"]["sha256"]:
            sys.exit("payload next to the inputs does not match them: %s" % got)

    name = "%s-%s" % (mi["from"]["buildmark"], mi["to"]["buildmark"])
    # The ipk is named after its target build alone, so two payloads to the same
    # build (600070-600120 and 600119-600120) share a file name. On the server each
    # is named after its route, ce-ota-<from>-<to>.ipk; the device still stages and
    # installs it as payload.file, the package name the OTA path has always used.
    served = "ce-ota-%s.ipk" % name
    manifest = {
        "format": FORMAT,
        "name": name,
        "tier": mi["tier"],
        "from": mi["from"],
        "to": mi["to"],
        "preflight": {"path": mi["preflight"]["path"], "md5": mi["preflight"]["md5"]},
        "payload": {
            "file": mi["payload"]["file"],
            # Relative: resolved against the server the device asked, so a host move
            # needs no re-signing. The sha256 is what makes the bytes trustworthy.
            "url": "/api/ce-ota/payloads/" + served,
            "size": mi["payload"]["size"],
            "sha256": mi["payload"]["sha256"],
            "md5": mi["payload"]["md5"],
        },
        "space": mi["space"],
        "offer": {
            "title": a.title or mi["to"]["version"],
            "installMinutes": a.install_minutes,
        },
    }
    body = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()

    os.makedirs(MANIFESTS, exist_ok=True)
    mpath = os.path.join(MANIFESTS, name + ".json")
    spath = mpath + ".sig"
    with open(mpath, "wb") as f:
        f.write(body)
    with tempfile.TemporaryDirectory() as tmp:
        der = os.path.join(tmp, "sig.der")
        subprocess.check_call(["openssl", "dgst", "-sha256", "-sign", KEY, "-out", der, mpath])
        with open(der, "rb") as f:
            sig = f.read()
        r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", PUB, "-signature", der, mpath],
                           capture_output=True, text=True)
        if r.returncode != 0:
            os.unlink(mpath)
            sys.exit("signature does not verify with %s: %s" % (PUB, r.stdout + r.stderr))
    with open(spath, "w") as f:
        # 64-column lines: what openssl enc -d -base64 (0.9.8k, on the device) reads.
        b = base64.b64encode(sig).decode()
        f.write("\n".join(b[i:i + 64] for i in range(0, len(b), 64)) + "\n")
    print("signed %s (%d bytes) and %s; verified with %s" % (mpath, len(body), spath, PUB))

    if a.copy_payload:
        if not os.path.exists(ipk):
            sys.exit("no payload at %s" % ipk)
        os.makedirs(PAYLOADS, exist_ok=True)
        shutil.copyfile(ipk, os.path.join(PAYLOADS, served))
        print("copied the payload to %s" % os.path.join(PAYLOADS, served))
    print("offered to nobody until ce-ota/releases.json names %s" % name)


if __name__ == "__main__":
    main()
