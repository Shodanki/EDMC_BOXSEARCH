# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The release manifest (4.12, integrity.py): SHA-256 of every file the
download carries - git's files without what .gitattributes marks
export-ignore (tests, CI, CONTRIBUTING ...). Line endings as LF.

    python tests/manifest.py            check: the manifest matches the files (CI)
    python tests/manifest.py --write    write it anew (after any change to a
                                        shipped file, and in the release commit)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH import integrity  # noqa: E402


def git(*args: str, data: str = None) -> str:
    """Output of one git command in the checkout."""
    # bytes, not text: on Windows text mode would send "\r\n" and git would
    # look up paths ending in "\r"
    raw = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, check=True,
                         input=data.encode("utf-8") if data is not None else None).stdout
    return raw.decode("utf-8").replace("\r\n", "\n")


def shipped() -> list:
    """Paths git tracks that the download carries (no export-ignore on the
    file or a folder above it), without the manifest itself."""
    files = [f for f in git("ls-files").splitlines() if f and f != integrity.MANIFEST]
    probe = set(files)
    for f in files:
        parts = f.split("/")
        probe.update("/".join(parts[:i]) for i in range(1, len(parts)))
    out = git("check-attr", "--stdin", "export-ignore", data="\n".join(sorted(probe)) + "\n")
    ignored = {ln.split(": ")[0] for ln in out.splitlines() if ln.endswith(": set")}

    def kept(f: str) -> bool:
        parts = f.split("/")
        return not any("/".join(parts[:i]) in ignored for i in range(1, len(parts) + 1))
    return sorted(f for f in files if kept(f) and os.path.isfile(os.path.join(ROOT, f)))


def build() -> str:
    """The manifest text for the files as they are now."""
    with open(os.path.join(ROOT, "state.py"), encoding="utf-8") as fh:
        version = next(ln.split('"')[1] for ln in fh if ln.startswith("VERSION = "))
    lines = [integrity.HEADER % version]
    for f in shipped():
        lines.append("%s  %s" % (integrity.file_hash(os.path.join(ROOT, *f.split("/"))), f))
    return "\n".join(lines) + "\n"


def main() -> int:
    """Check (default) or --write."""
    text = build()
    path = os.path.join(ROOT, integrity.MANIFEST)
    if "--write" in sys.argv:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        print("manifest written: %d files" % (len(text.splitlines()) - 1))
        return 0
    try:
        with open(path, encoding="utf-8") as fh:
            have = fh.read().replace("\r\n", "\n")
    except OSError:
        have = ""
    ok = have == text
    print("  [%s] %s lists every shipped file with its current hash (%d files)"
          % ("OK" if ok else "FAIL", integrity.MANIFEST, len(text.splitlines()) - 1))
    if not ok:
        old = set(have.splitlines())
        for ln in text.splitlines():
            if ln not in old:
                print("        new/changed: " + ln[66:] if len(ln) > 66 else "        " + ln)
        print("  run: python tests/manifest.py --write")
    res = integrity.check(ROOT)
    print("  [%s] integrity.check on this checkout: %s" % ("OK" if res["ok"] else "FAIL",
                                                           integrity.summary(res) or "all files as listed"))
    fails = (not ok) + (not res["ok"])
    print("manifest: %s" % ("all OK" if not fails else "%d FAILED" % fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
