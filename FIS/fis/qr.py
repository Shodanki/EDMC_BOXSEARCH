# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""QR code of the home-network address as SVG (settings page, game PC only).

The encoder is Project Nayuki's qrcodegen (MIT, fis/vendor/SOURCE.md); this
module only draws the modules as one SVG path - dark on white, with the
quiet zone the standard asks for, so phone and tablet cameras read it."""

from __future__ import annotations

from .vendor.qrcodegen import QrCode

BORDER = 4      # quiet zone in modules (QR standard)


def svg(text: str, border: int = BORDER) -> str:
    """SVG text for `text` (error correction M: still readable from a screen
    with glare, small enough for a long URL with token)."""
    qr = QrCode.encode_text(text, QrCode.Ecc.MEDIUM)
    n = qr.get_size()
    size = n + 2 * border
    parts = []
    for y in range(n):
        for x in range(n):
            if qr.get_module(x, y):
                parts.append("M%d,%dh1v1h-1z" % (x + border, y + border))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
            'viewBox="0 0 %d %d" stroke="none" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="#FFFFFF"/>'
            '<path d="%s" fill="#000000"/></svg>\n') % (size, size, " ".join(parts))
