# qrcodegen.py - third-party code, shipped unchanged

* Project: QR Code generator library (Python) by Project Nayuki -
  https://www.nayuki.io/page/qr-code-generator-library -
  https://github.com/nayuki/QR-Code-generator
* Licence: MIT, "Copyright (c) Project Nayuki." - the full licence text is
  kept as the header of `qrcodegen.py` and must stay there.
* Version: the single-file Python library as published by Project Nayuki
  (PyPI package `qrcodegen`, release line 1.8); copied unchanged on
  10.11.2026. SHA-256 of the file:
  `9f4ed1dd201dcb92b1bc0d6e14f46c754bcff0ce48580c5d7e8ace8f6926c8ef`
* Uses only the Python standard library (collections, itertools, re, typing).

Used by `fis/qr.py` to show the home-network address of the FIS as a QR code
on the settings page (game PC only), so a tablet can open it with its camera.
The SVG drawing is our own code in `fis/qr.py`. To update: replace
`qrcodegen.py` with a newer file of the same project and change this note.
