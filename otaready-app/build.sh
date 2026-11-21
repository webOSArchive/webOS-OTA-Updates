#!/bin/bash
# Build the "Get Ready for OTA" ipk (hand-built with ar/tar; no Palm SDK needed).
# The canonical fingerprint.sh is copied in as the device helper so there is one
# source of truth. Install the result via Preware or WebOS Quick Install (NOT
# palm-install — the postinst must run as root).
set -e

APPID=org.webosarchive.otaready
SVCID=org.webosarchive.otaready.service
VERSION=$(sed -n 's/.*"version"[ ]*:[ ]*"\([0-9.]*\)".*/\1/p' "$(cd "$(dirname "$0")" && pwd)/org.webosarchive.otaready/appinfo.json")
HERE=$(cd "$(dirname "$0")" && pwd)
APPDIR="$HERE/$APPID"
SVCDIR="$HERE/$SVCID"
OUT="$HERE/${APPID}_${VERSION}_all.ipk"

for f in otaready-daemon otaready-daemon.conf ota-manifest.js UpdatesApp.patched.js; do
    [ -f "$APPDIR/device/$f" ] || { echo "ERROR: device/$f missing"; exit 1; }
done
sh -n "$APPDIR/device/otaready-daemon" || { echo "ERROR: otaready-daemon does not parse"; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# 2. stage the data root. OFFLINE-ROOT RULE: data.tar.gz is rooted at
#    ./usr/palm/{applications,services}/<id>/... (the installer extracts it under
#    /media/cryptofs/apps), so do NOT include media/cryptofs/apps/ in the path.
STAGE="$WORK/data/usr/palm/applications/$APPID"
STAGE_SVC="$WORK/data/usr/palm/services/$SVCID"
mkdir -p "$STAGE" "$STAGE_SVC"
cp -a "$APPDIR/." "$STAGE/"
cp -a "$SVCDIR/." "$STAGE_SVC/"
( cd "$WORK/data" && tar --owner=0 --group=0 -czf "$WORK/data.tar.gz" . )

# 3. control.tar.gz = control + postinst + prerm (0755 scripts)
mkdir -p "$WORK/control"
cat > "$WORK/control/control" <<CTRL
Package: $APPID
Version: $VERSION
Section: Application
Priority: optional
Architecture: all
Installed-Size: 1
Maintainer: webOS Archive
Description: OTA Ready - lets System Updates install webOS CE updates from the community update server (webOS CE 3.1.0 and later).
webOS-Package-Format-Version: 2
webOS-Packager-Version: 3.0.5b38
CTRL
cp "$HERE/control/postinst" "$WORK/control/postinst"
cp "$HERE/control/prerm"    "$WORK/control/prerm"
chmod 755 "$WORK/control/postinst" "$WORK/control/prerm"
( cd "$WORK/control" && tar --owner=0 --group=0 -czf "$WORK/control.tar.gz" ./control ./postinst ./prerm )

# 4. assemble the ipk (member order matters: debian-binary, control, data)
echo "2.0" > "$WORK/debian-binary"
rm -f "$OUT"
( cd "$WORK" && ar rc "$OUT" debian-binary control.tar.gz data.tar.gz )

echo "Built: $OUT"
echo "Members:"; ar t "$OUT"
echo
echo "Install via Preware or WebOS Quick Install (NOT palm-install — postinst needs root)."
