# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
ai-disclosure.json names AI_TRANSPARENCY.md by its SHA-256 (M14, 5.0.1).

The hash had stayed at the text of 4.6 since 4.7.0 (audit 21.11.); now CI
compares it, line endings as LF like tests/manifest.py.

    python tests/ai_disclosure.py            check (CI)
    python tests/ai_disclosure.py --write    set the hash after a change to the text
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON = os.path.join(ROOT, "ai-disclosure.json")


def digest(path: str) -> str:
    """SHA-256 of a text file with LF line endings."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def main(argv) -> int:
    with open(JSON, encoding="utf-8") as fh:
        meta = json.load(fh)
    want = digest(os.path.join(ROOT, meta["document"]))
    if "--write" in argv:
        with open(JSON, encoding="utf-8") as fh:
            text = fh.read()
        if meta["sha256"] != want:
            text = text.replace(meta["sha256"], want)
            with open(JSON, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        print("ai-disclosure.json: sha256 %s" % want)
        return 0
    if meta["sha256"] != want:
        print("ai-disclosure.json: sha256 %s, but %s is %s - run python tests/ai_disclosure.py --write"
              % (meta["sha256"], meta["document"], want))
        return 1
    print("ai-disclosure.json: hash of %s ok" % meta["document"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
