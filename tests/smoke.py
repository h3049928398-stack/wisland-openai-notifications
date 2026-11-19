"""Boot an isolated release installation through wisland.app.main and exit through Qt."""
import ctypes
import os
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch

from PySide6 import QtCore, QtWidgets

target = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
from wisland import app
from wisland.services import openai_notifications as ai
from wisland.ui.island import Island

original_exec = QtWidgets.QApplication.exec
failures = []


def check():
    try:
        island = next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, Island))
        pages = {p.key: p for p in island.pages}
        msg = pages["msg"]
        island.expand("msg")
        service = msg.ctx.notify
        service._on_ai_toast("codex", "任务完成", time.time())
        service._on_ai_toast("chatgpt", "新消息", time.time())
        msg.refresh()
        assert msg.tiles["codex"].count == 1 and msg.tiles["chatgpt"].count == 1
        assert island.nav.badges["msg"] == 2 and island.compact.badges == service.counts
        assert island.compact.activity["title"] == "ChatGPT"
        control = next(p for p in pages.values() if type(p).__name__ == "ControlsPage")
        island.show_page(control.key)
        control.on_show()
        control.on_hide()
        if os.getenv("WISLAND_TEST_ACTIVATE"):
            for kind in ("chatgpt", "codex"):
                msg.tiles[kind].clicked.emit()
                QtWidgets.QApplication.processEvents()
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                assert ai.window_is_client(hwnd), "registered client did not gain focus"
                assert service.counts[kind] == 0
        print("PASS normal startup, page, activity, badges, controls", flush=True)
    except BaseException:
        traceback.print_exc()
        failures.append(True)
    finally:
        QtWidgets.QApplication.quit()


def event_loop(_application):
    QtCore.QTimer.singleShot(400, check)
    return original_exec()


# An isolated test installation must not update the user's actual startup shortcut.
with patch.object(app, "fix_autostart"), patch.object(QtWidgets.QApplication, "exec", event_loop):
    status = app.main()
sys.exit(int(bool(failures)) or status)
