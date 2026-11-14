# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""4.12: the file check at every FIS start (fis/files.py)."""
import os
import shutil
import tempfile
import unittest

from fis import files


def copy_download(dest):
    """The plugin's shipped files as the manifest lists them, and the manifest."""
    mod = files._integrity()
    _version, listed = mod.load_manifest(files.PLUGIN_ROOT)
    for rel in listed:
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(files.PLUGIN_ROOT, *rel.split("/")), target)
    shutil.copyfile(os.path.join(files.PLUGIN_ROOT, mod.MANIFEST), os.path.join(dest, mod.MANIFEST))


class FilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root = os.path.join(cls.tmp, "SHBOXSEARCH")
        copy_download(cls.root)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def tearDown(self):
        files.RESULT.clear()
        files.RESULT.update({"ok": True, "checked": False})

    def test_all_there_says_nothing(self):
        lines = []
        res = files.startup_check(lines.append, root=self.root)
        self.assertTrue(res["ok"])
        self.assertEqual(lines, [])
        self.assertTrue(files.for_browser()["ok"])

    def test_missing_and_changed_in_both_languages(self):
        js = os.path.join(self.root, "FIS", "web", "js", "app.js")
        os.rename(js, js + ".x")
        with open(os.path.join(self.root, "FIS", "fis", "model.py"), "a", encoding="utf-8") as fh:
            fh.write("# changed\n")
        try:
            lines = []
            res = files.startup_check(lines.append, root=self.root)
        finally:
            os.rename(js + ".x", js)
            shutil.copyfile(os.path.join(files.PLUGIN_ROOT, "FIS", "fis", "model.py"),
                            os.path.join(self.root, "FIS", "fis", "model.py"))
        self.assertFalse(res["ok"])
        text = "\n".join(lines)
        self.assertIn("1 missing", text)
        self.assertIn("1 fehlen", text)
        self.assertIn("release ZIP", text)
        self.assertIn("Release-ZIP", text)
        self.assertIn("FIS/web/js/app.js", text)
        self.assertIn("FIS/fis/model.py", text)
        b = files.for_browser()
        self.assertEqual((b["ok"], b["n_missing"], b["n_changed"]), (False, 1, 1))
        self.assertNotIn(self.root, str(b))           # names only, no paths of this PC

    def test_check_itself_missing(self):
        os.rename(os.path.join(self.root, "integrity.py"), os.path.join(self.root, "i.bak"))
        try:
            res = files.check(self.root)
        finally:
            os.rename(os.path.join(self.root, "i.bak"), os.path.join(self.root, "integrity.py"))
        self.assertFalse(res["ok"])
        self.assertEqual(res["missing"], ["integrity.py"])
        self.assertIn("fehlt", files.german(res))

    def test_cannot_start_names_the_remedy(self):
        lines = []
        files.cannot_start(ImportError("No module named 'fis.model'"), lines.append)
        self.assertIn("fis.model", lines[0])
        self.assertTrue(any("release ZIP" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
