"""Every text of the web UI has a German translation (EN is the key)."""

import glob
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

_STR = r'"((?:[^"\\]|\\.)*)"'
_CALL = re.compile(r'\b(?:t|N_)\(\s*' + _STR)
# t(cond ? "a" : "b", ...)
_TERN = re.compile(r'\bt\(\s*[^"()]*\?\s*' + _STR + r'\s*:\s*' + _STR)
_ATTR = re.compile(r'data-i18n(?:-title)?="([^"]+)"')


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def used_keys():
    keys = []
    for f in glob.glob(os.path.join(WEB, "js", "**", "*.js"), recursive=True):
        if f.endswith("i18n.js"):
            continue
        s = _read(f)
        keys += [json.loads('"%s"' % m.group(1)) for m in _CALL.finditer(s)]
        for m in _TERN.finditer(s):
            keys += [json.loads('"%s"' % m.group(1)), json.loads('"%s"' % m.group(2))]
    keys += _ATTR.findall(_read(os.path.join(WEB, "index.html")))
    out = []
    for k in keys:
        if k not in out:
            out.append(k)
    return out


def german():
    s = _read(os.path.join(WEB, "js", "i18n.js"))
    body = s[s.index("/*DE*/") + 6:s.index("/*END*/")]
    return json.loads(body)


class I18nTest(unittest.TestCase):
    def test_every_text_has_german(self):
        de = german()
        missing = [k for k in used_keys() if k not in de]
        self.assertEqual(missing, [], "missing German entries:\n" + "\n".join(missing))

    def test_placeholders_match(self):
        for en, de in german().items():
            self.assertEqual(sorted(re.findall(r"\{\w+\}", en)), sorted(re.findall(r"\{\w+\}", de)),
                             "placeholders differ: %r -> %r" % (en, de))

    def test_no_unused_entries(self):
        used = set(used_keys())
        unused = [k for k in german() if k not in used]
        self.assertEqual(unused, [], "German entries nobody uses:\n" + "\n".join(unused))

    def test_t_is_never_shadowed(self):
        """A local `const t = ...` in a module that imports t() breaks every text there."""
        for f in glob.glob(os.path.join(WEB, "js", "**", "*.js"), recursive=True):
            s = _read(f)
            if not re.search(r"import\s*\{[^}]*\bt\b[^}]*\}\s*from", s):
                continue
            hits = re.findall(r"\b(?:const|let|var)\s+t\s*=|\(\s*t\s*[,)]\s*=>|\bfunction\s*\w*\s*\(\s*t\s*[,)]", s)
            self.assertEqual(hits, [], os.path.basename(f))

    def test_no_german_left_in_views(self):
        """Umlauts outside i18n.js / ui.js (planet class table) point at missed texts."""
        for f in glob.glob(os.path.join(WEB, "js", "**", "*.js"), recursive=True):
            if f.endswith(("i18n.js", "ui.js")):
                continue
            for i, line in enumerate(_read(f).splitlines(), 1):
                code = line.split("//", 1)[0]
                self.assertIsNone(re.search(r'"[^"]*[äöüÄÖÜß][^"]*"', code),
                                  "%s:%d %s" % (os.path.basename(f), i, line.strip()))


if __name__ == "__main__":  # pragma: no cover
    for k in used_keys():
        print(json.dumps(k, ensure_ascii=False))
