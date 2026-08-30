# CE OTA signing key

`ce-ota-signing.pub` is the trust anchor baked into the 3.1.0 system image at
`/usr/share/ce-ota/keys/ce-ota-signing.pub`. It is the root of trust for every
OTA payload; see `../OTA-3.1.0.md` Part II.

- Algorithm: **RSA-4096**, signatures **SHA-256, PKCS#1 v1.5** (`openssl dgst -sha256 -sign`).
- Chosen for compatibility with the stock **OpenSSL 0.9.8k (2009)** at `/usr/bin/openssl`,
  which is what both webOS 3.0.5 and CE 3.1.0 ship. Verified on hardware 2026-08-30.
- Verifier: `../webos-update-server/device-scripts/ce-ota-verify`.

Fingerprint (SHA-256 of the DER SubjectPublicKeyInfo) is in
`ce-ota-signing.pub.sha256`. Check a device's baked copy against it:

    # build host (OpenSSL 1.x):
    openssl pkey -pubin -in ce-ota-signing.pub -outform DER | openssl dgst -sha256 -c

    # on a device: stock openssl is 0.9.8k and has no `pkey` (added in 1.0.0)
    openssl rsa -pubin -in /usr/share/ce-ota/keys/ce-ota-signing.pub \
      -outform DER | openssl dgst -sha256 -c

**The private half is NOT in this repository and must never be.** It lives only on
the signing host.
