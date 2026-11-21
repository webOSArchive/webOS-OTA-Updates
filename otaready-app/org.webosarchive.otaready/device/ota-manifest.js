// ota-manifest.js: read a CE OTA manifest that ce-ota-verify has ALREADY accepted
// and print it as shell assignments for otaready-daemon to eval.
//
//   node ota-manifest.js <manifest.json>
//
// Runs on the device's node 0.4. Every value is checked against a pattern before
// it is printed, so nothing in a manifest (even a correctly signed one with a
// mistake in it) can reach the shell as code. Unknown fields are ignored, so a
// later manifest can add fields an older client does not know (forward
// compatibility); a missing or malformed known field is a refusal. Fields are
// read with hasOwnProperty only, never through the prototype chain.
//
// Exit 0 and the assignments on stdout, or exit 1 and the reason on stderr.

var fs = require("fs");

var SUPPORTED_FORMAT = 1;

function own(o, k) { return o !== null && typeof o === "object" && Object.prototype.hasOwnProperty.call(o, k); }
function fail(why) { process.stderr.write("ota-manifest: " + why + "\n"); process.exit(1); }

function get(o, path) {
    var parts = path.split("."), i;
    for (i = 0; i < parts.length; i++) {
        if (!own(o, parts[i])) { fail("missing " + path); }
        o = o[parts[i]];
    }
    return o;
}

function str(o, path, re) {
    var v = get(o, path);
    if (typeof v === "number") { v = String(v); }
    if (typeof v !== "string" || !re.test(v)) { fail("bad " + path); }
    return v;
}

function num(o, path) {
    var v = get(o, path);
    if (typeof v !== "number" || v < 0 || v > 2147483647 || Math.floor(v) !== v) { fail("bad " + path); }
    return v;
}

var file = process.argv[2];
if (!file) { fail("usage: node ota-manifest.js <manifest.json>"); }
var m;
try { m = JSON.parse(fs.readFileSync(file, "utf8")); } catch (e) { fail("unreadable: " + e); }

if (get(m, "format") !== SUPPORTED_FORMAT) { fail("format " + m.format + " is not one this client knows"); }

var BUILD = /^[0-9]{1,12}$/;
var HEX32 = /^[0-9a-f]{32}$/;
var HEX64 = /^[0-9a-f]{64}$/;
var FILE = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/;
var PATH = /^\/[A-Za-z0-9._+\/-]{1,255}$/;
var URL = /^(\/api\/ce-ota\/payloads\/[A-Za-z0-9._+-]{1,128}|https:\/\/[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?\/[A-Za-z0-9._+\/-]{1,255})$/;
var TEXT = /^[A-Za-z0-9 .,()+:\/-]{1,64}$/;

var out = {
    M_NAME: str(m, "name", /^[A-Za-z0-9._-]{1,64}$/),
    M_TIER: str(m, "tier", /^[a-z-]{1,32}$/),
    M_FROM: str(m, "from.buildmark", BUILD),
    M_TO: str(m, "to.buildmark", BUILD),
    M_TO_VERSION: str(m, "to.version", TEXT),
    M_PREFLIGHT_PATH: str(m, "preflight.path", PATH),
    M_PREFLIGHT_MD5: str(m, "preflight.md5", HEX32),
    M_FILE: str(m, "payload.file", FILE),
    M_URL: str(m, "payload.url", URL),
    M_SIZE: num(m, "payload.size"),
    M_SHA256: str(m, "payload.sha256", HEX64),
    M_MD5: str(m, "payload.md5", HEX32),
    M_ROOTFS_GROWTH: num(m, "space.rootfs_growth"),
    M_LARGEST_FILE: num(m, "space.largest_file"),
    M_TITLE: str(m, "offer.title", TEXT),
    M_MINUTES: num(m, "offer.installMinutes")
};
if (out.M_PREFLIGHT_PATH.indexOf("..") >= 0 || out.M_URL.indexOf("..") >= 0) { fail("dot-dot in a path"); }

var k, lines = [];
for (k in out) {
    if (own(out, k)) { lines.push(k + "='" + out[k] + "'"); }   // no value can hold a quote
}
process.stdout.write(lines.join("\n") + "\n");
