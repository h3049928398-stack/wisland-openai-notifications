"""Build the release ZIP from the audited payload allowlist."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
META = ROOT / "openai-notifications"


def build():
    manifest = json.loads((META / "manifest.json").read_text("utf-8"))
    files = {}
    for name, info in manifest["files"].items():
        data = (ROOT / "overlay" / name).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != info["release"]:
            raise ValueError(f"Update the reviewed manifest for {name}")
        files[name] = data
    for name in ("README.md", "LICENSE", "VALIDATION.md"):
        files["openai-notifications/" + name] = (ROOT / name).read_bytes()
    for name in ("install.py", "manifest.json"):
        files["openai-notifications/" + name] = (META / name).read_bytes()
    out = ROOT / "dist" / f"wisland-openai-notifications-v{manifest['version']}.zip"
    out.parent.mkdir(exist_ok=True)
    with ZipFile(out, "w") as archive:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, (2026, 11, 19, 0, 0, 0))
            archive.writestr(info, data.replace(b"\r\n", b"\n"), compress_type=ZIP_DEFLATED)
    print(out)
    return out


if __name__ == "__main__":
    build()
