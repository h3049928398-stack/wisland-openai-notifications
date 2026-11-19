"""Install or restore this overlay in a separate Wisland directory (Python 3.10+)."""
import argparse
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import tempfile
from datetime import datetime

HERE = Path(__file__).resolve().parent
FILES = ("wisland/app.py", "wisland/services/notify.py", "wisland/services/openai_notifications.py",
         "wisland/ui/compact.py", "wisland/ui/pages/home.py", "wisland/ui/theme.py")


def digest(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() if data is not None else None


def contents(path):
    return path.read_bytes() if path.exists() else None


def within(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path outside target: {relative}")
    return path


def replace(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(data)
        except BaseException:
            f.close()
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def apply(target, before, after):
    written = []
    try:
        for name, value in after.items():
            if before[name] == value:
                continue
            path = within(target, name)
            if contents(path) != before[name]:
                raise ValueError(f"File changed during installation: {name}")
            replace(path, value)
            written.append(name)
    except BaseException:
        for name in reversed(written):
            replace(within(target, name), before[name])
        raise


def run(target, rollback=None):
    target = target.resolve()
    if not (target / "wisland.vbs").is_file():
        raise ValueError("Select the directory containing wisland.vbs")
    store = within(target, "data/extension-backups/openai-notifications")
    store.mkdir(parents=True, exist_ok=True)
    with (store / "install.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        before = {n: contents(within(target, n)) for n in FILES}
        if rollback:
            backup = within(store, rollback)
            record = json.loads((backup / "backup.json").read_text("utf-8"))
            after = {}
            for n in FILES:
                info = record[n]
                after[n] = contents(within(backup, n))
                if digest(after[n]) != info["before"] or digest(before[n]) not in (info["after"], info["before"]):
                    raise ValueError(f"Backup mismatch or modified file: {n}")
            apply(target, before, after)
            return f"Restored {backup.name}"

        manifest = json.loads((HERE / "manifest.json").read_text("utf-8"))
        payload = HERE.parent / "overlay"
        if not payload.is_dir():
            payload = HERE.parent
        after = {}
        for n in FILES:
            info = manifest["files"][n]
            after[n] = (payload / n).read_bytes()
            if digest(after[n]) != info["release"]:
                raise ValueError(f"Package mismatch: {n}")
            if digest(before[n]) not in (*info["accepted"], info["release"]):
                raise ValueError(f"Unsupported or locally modified: {n}")
        if all(digest(before[n]) == digest(after[n]) for n in FILES):
            return "Already installed"
        backup = store / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup.mkdir()
        for n in FILES:
            if before[n] is not None:
                path = backup / n
                path.parent.mkdir(exist_ok=True, parents=True)
                path.write_bytes(before[n])
        record = {n: {"before": digest(before[n]), "after": digest(after[n])} for n in FILES}
        (backup / "backup.json").write_text(json.dumps(record, indent=2), "utf-8")
        apply(target, before, after)
        return f"Installed. Backup: {backup.name}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--rollback", metavar="BACKUP")
    args = parser.parse_args()
    try:
        print(run(args.target, args.rollback))
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"{error}\n")
