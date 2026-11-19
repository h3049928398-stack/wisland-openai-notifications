"""Metadata-only classification of notifications from the unified Windows client."""
from __future__ import annotations

import ctypes
import datetime as dt
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
from ctypes import wintypes
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

APP_ID = "OpenAI.Codex_2p2nqsd0c76g0!App"
SHARED = "openai"
NAMES = {"chatgpt": "ChatGPT", "codex": "Codex", SHARED: "ChatGPT / Codex"}
UUID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
SHOW = "[desktop-notifications] show notification "
MAX_DELAY = 0.25


def window_is_client(hwnd):
    """Check the process AUMID, including on versions using ChatGPT.exe."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    kernel.OpenProcess.restype = wintypes.HANDLE
    process = kernel.OpenProcess(0x1000, False, pid.value)
    if not process:
        return False
    handle = wintypes.HANDLE(process)
    try:
        size = wintypes.UINT(512)
        name = ctypes.create_unicode_buffer(size.value)
        status = kernel.GetApplicationUserModelId(handle, ctypes.byref(size), name)
        return status == 0 and name.value.casefold() == APP_ID.casefold()
    finally:
        kernel.CloseHandle(handle)


def route_kind(value):
    """Only explicit, complete first-party conversation activation targets qualify."""
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme == "https" and url.netloc.lower() == "chatgpt.com" and re.fullmatch("/c/" + UUID + "/?", url.path):
        return "chatgpt"
    if url.scheme == "codex" and url.netloc == "threads" and re.fullmatch("/" + UUID + "/?", url.path):
        return "codex"
    return None


def toast_metadata(payload):
    """Ignore all visible text. Extract activation route or a supported native action shape."""
    if not payload or len(payload) > 128 * 1024:
        return None, None
    try:
        root = ET.fromstring(payload)
    except (ET.ParseError, ValueError, LookupError):
        return None, None
    launch = root.get("launch", "")
    actions = root.findall("./actions/action")
    args = parse_qs(launch)
    routes = {source for value in [launch, *args.get("url", []), *args.get("uri", [])]
              if (source := route_kind(value))}
    if len(routes) == 1:
        return routes.pop(), None
    tag = args.get("tag")
    if routes or args.get("type") != ["click"] or not tag or len(tag) != 1 or len(actions) != 1:
        return None, None
    action = actions[0]
    inputs = root.findall("./actions/input")
    reply = parse_qs(action.get("arguments", ""))
    if (len(inputs) == 1 and inputs[0].get("type") == "text"
            and inputs[0].get("id") == action.get("hint-inputId")
            and reply.get("type") == ["reply"] and reply.get("tag") == tag):
        return None, "turn-complete"
    if not inputs and action.get("arguments") == "dismiss":
        return None, "question"
    return None, None


def delivered_event(line):
    """Use the main-process dispatch record, never renderer intentions or chat text."""
    if SHOW not in line:
        return None
    prefix, fields = line.split(SHOW, 1)
    if not fields.startswith("actionCount="):
        return None
    fields = dict(re.findall(r"\b(actionCount|kind|notificationId)=(\S+)", fields))
    stamp = re.search(r"\d{4}-\d\d-\d\dT[\d:.]+Z", prefix)
    if not stamp:
        return None
    try:
        when = dt.datetime.fromisoformat(stamp[0].replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
    kind = fields.get("kind")
    key = fields.get("notificationId", "")
    prefix = {"turn-complete": "turn-", "question": "async-question-"}.get(kind)
    thread = None
    if prefix and key.startswith(prefix) and fields.get("actionCount") == "0":
        try:
            parts = json.loads(key[len(prefix):])
            if (isinstance(parts, list) and len(parts) >= 5 and parts[2] == "local"
                    and re.fullmatch(UUID, str(parts[3])) and re.fullmatch(UUID, str(parts[4]))):
                thread = parts[3]
        except (ValueError, TypeError):
            pass
    # Unknown dispatches also participate in the ambiguity check.
    return when, kind, thread


def read_dispatches(log_root, begin, end):
    # Files rotate by local calendar day; also check UTC around midnight.
    days = {ctor(t).strftime("%Y/%m/%d") for ctor in
            (dt.datetime.fromtimestamp, lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc))
            for t in (begin - 1, end + 1)}
    events = []
    for day in days:
        for path in (log_root / day).glob("*.log"):
            if path.stat().st_mtime < begin - 2:
                continue
            with path.open("rb") as stream:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 256 * 1024))
                if stream.tell():
                    stream.readline()
                for line in stream:
                    if b"[desktop-notifications] show notification actionCount=" in line:
                        event = delivered_event(line.decode("utf-8", "replace"))
                        if event and begin - MAX_DELAY <= event[0] <= end:
                            events.append(event)
    return events


def classify_batch(toasts, log_root=None, state_path=None):
    """Map WPN row IDs to (kind, short description). All I/O runs on the poll worker."""
    result = {}
    pending = []
    for row_id, when, payload in toasts:
        kind, shape = toast_metadata(payload)
        result[row_id] = kind or SHARED, "新消息"
        if shape:
            pending.append((row_id, when, shape))
    if not pending:
        return result

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    log_root = log_root or local / "Packages" / APP_ID.split("!")[0] / "LocalCache/Local/Codex/Logs"
    state_path = state_path or Path(os.getenv("CODEX_HOME") or Path.home() / ".codex") / "state_5.sqlite"
    try:
        times = [t[1] for t in pending]
        events = read_dispatches(log_root, min(times), max(times))
        if not events:
            return result
        con = sqlite3.connect(state_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.15)
        try:
            for row_id, arrival, shape in pending:
                matches = [ev for ev in events if 0 <= arrival - ev[0] <= MAX_DELAY]
                if len(matches) != 1:
                    continue
                stamp, event_type, thread = matches[0]
                if (shape != event_type or not thread
                        or sum(0 <= when - stamp <= MAX_DELAY for _, when, _ in toasts) != 1):
                    continue
                origin = con.execute("SELECT originator, thread_source FROM threads WHERE id=?", (thread,)).fetchone()
                source = {("Codex Desktop", "user"): "codex",
                          ("codex_work_desktop", "user"): "chatgpt"}.get(origin)
                if source:
                    result[row_id] = source, "任务完成" if shape == "turn-complete" else "需要输入"
        finally:
            con.close()
    except (OSError, sqlite3.Error, ValueError, OverflowError):
        pass
    return result
