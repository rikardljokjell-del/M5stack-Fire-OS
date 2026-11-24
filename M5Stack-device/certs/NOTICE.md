# Public trust assets

`roots.bundle` contains public root-certificate subjects and public keys from
Mozilla's trust list distributed by certifi 2026.11.20. It contains no private
keys or local Home Assistant credentials. `roots.json` records its count and
SHA256. The generation recipe is `tools/refresh_trust.py` and follows ESP-IDF
4.4.6's compact bundle format. Ordinary builds use this committed asset.

Sources and licensing: [certifi](https://github.com/certifi/python-certifi),
[Mozilla Public License 2.0](https://www.mozilla.org/MPL/2.0/),
[ESP-IDF bundle generator](https://github.com/espressif/esp-idf/blob/v4.4.6/components/mbedtls/esp_crt_bundle/gen_crt_bundle.py).

`release-public.pem` is the publisher's P-256 verification key, pinned in the
firmware and PC migration tool. Its matching private key is local only and
must never be included in this directory, a release or source control.
