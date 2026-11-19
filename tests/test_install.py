"""Installer transactions against temporary directories with isolated fixture manifests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "openai-notifications"))
import install


class Installer(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.dest = root / "target"
        meta = root / "package/openai-notifications"
        meta.mkdir(parents=True)
        self.dest.mkdir()
        (self.dest / "wisland.vbs").touch()
        self.original = {}
        files = {}
        for i, name in enumerate(install.FILES):
            old = None if i == 2 else f"base {i}\r\n".encode()
            self.original[name] = old
            dst = self.dest / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if old:
                dst.write_bytes(old)
            new = f"release {i}\n".encode()
            source = meta.parent / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(new)
            files[name] = {"accepted":[install.digest(old)],"release":install.digest(new)}
        (meta / "manifest.json").write_text(json.dumps({"files":files}), "utf-8")
        patcher = patch.object(install,"HERE",meta)
        patcher.start()
        self.addCleanup(patcher.stop)

    def snapshot(self):
        return {n:install.contents(self.dest/n) for n in install.FILES}

    def test_reinstall_and_restore(self):
        user_config = self.dest/"config.json"
        user_config.write_bytes(b'{"fixture":true}')
        backup = install.run(self.dest).split()[-1]
        self.assertEqual(install.run(self.dest),"Already installed")
        install.run(self.dest,backup)
        self.assertEqual(self.snapshot(),self.original)
        self.assertEqual(user_config.read_bytes(),b'{"fixture":true}')

    def test_conflict_before_install(self):
        (self.dest/install.FILES[-1]).write_bytes(b"local")
        expected = self.snapshot()
        with self.assertRaises(ValueError):
            install.run(self.dest)
        self.assertEqual(self.snapshot(),expected)

    def test_conflict_before_restore(self):
        backup = install.run(self.dest).split()[-1]
        (self.dest/install.FILES[-1]).write_bytes(b"local")
        expected = self.snapshot()
        with self.assertRaises(ValueError):
            install.run(self.dest,backup)
        self.assertEqual(self.snapshot(),expected)

    def test_partial_failure_restores_originals(self):
        original_replace = install.replace
        def fail(path, data):
            if path == self.dest/install.FILES[-1]:
                raise OSError("simulated replace failure")
            original_replace(path,data)
        with patch.object(install,"replace",side_effect=fail), self.assertRaises(OSError):
            install.run(self.dest)
        self.assertEqual(self.snapshot(),self.original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
