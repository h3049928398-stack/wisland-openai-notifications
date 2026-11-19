"""Run against a separate Wisland target with the release ZIP already extracted."""
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TARGET = Path(os.environ["WISLAND_TEST_TARGET"]).resolve()
sys.path.insert(0, str(TARGET))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from wisland.services import notify, openai_notifications as ai
from wisland.ui.compact import CompactView
from wisland.ui.pages.home import MessagesPage
from wisland.ui.theme import theme

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
THREAD = "00000000-0000-4000-8000-000000000001"
TURN = "00000000-0000-4000-8000-000000000002"
REPLY = ('<toast launch="type=click&amp;tag=test"><actions><input id="a" type="text"/>'
         '<action arguments="type=reply&amp;tag=test" hint-inputId="a"/></actions></toast>')
FILETIME = 116444736000000000


class Classifier(unittest.TestCase):
    def test_activation(self):
        for url, kind in [(f"https://chatgpt.com/c/{THREAD}", "chatgpt"),
                          (f"codex://threads/{THREAD}", "codex")]:
            self.assertEqual(ai.toast_metadata(f'<toast launch="{url}"/>')[0], kind)

    def test_fallback(self):
        for sample in [b"broken", b'<toast><text>Codex ChatGPT</text></toast>',
                       f'<toast launch="https://chatgpt.com.example/c/{THREAD}"/>']:
            self.assertEqual(ai.classify_batch([(1, time.time(), sample)])[1][0], ai.SHARED)

    def test_correlated_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = dt.datetime.now(dt.timezone.utc)
            stamp = now.timestamp()
            day = root / now.strftime("%Y/%m/%d")
            day.mkdir(parents=True)
            db = root / "state.sqlite"
            con = sqlite3.connect(db)
            con.execute("create table threads(id text, originator text, thread_source text)")
            con.execute("insert into threads values (?, 'Codex Desktop', 'user')", (THREAD,))
            con.commit()
            con.close()
            fields = json.dumps(["example", "example", "local", THREAD, TURN], separators=(",", ":"))
            line = (now.isoformat().replace("+00:00", "Z") + " info " + ai.SHOW +
                    "actionCount=0 kind=turn-complete notificationId=turn-" + fields + "\n")
            log = day / "client.log"
            log.write_text(line, "utf-8")
            toast = (1, stamp + .02, REPLY)
            self.assertEqual(ai.classify_batch([toast], root, db)[1], ("codex", "任务完成"))
            with sqlite3.connect(db) as work:
                work.execute("update threads set originator='codex_work_desktop'")
            work.close()
            self.assertEqual(ai.classify_batch([toast], root, db)[1], ("chatgpt", "任务完成"))
            self.assertEqual(ai.classify_batch([toast, (2, stamp + .04, REPLY)], root, db)[1][0], ai.SHARED)
            self.assertEqual(ai.classify_batch([(1, stamp + 1, REPLY)], root, db)[1][0], ai.SHARED)
            self.assertEqual(ai.classify_batch([toast], root, root / "absent")[1][0], ai.SHARED)
            log.write_text(line * 2, "utf-8")
            self.assertEqual(ai.classify_batch([toast], root, db)[1][0], ai.SHARED)
            log.write_text(line.replace(THREAD, TURN), "utf-8")
            self.assertEqual(ai.classify_batch([toast], root, db)[1][0], ai.SHARED)


class Service(unittest.TestCase):
    def setUp(self):
        self.s = notify.NotifyService()
        self.s._running = True
        self.seen = []
        self.s.notified.connect(self.seen.append)

    def tearDown(self):
        self.s.stop()

    def test_cursor_and_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wpn.sqlite"
            c = sqlite3.connect(path)
            c.executescript("create table Notification(Id integer, HandlerId int, ArrivalTime integer, Type text, Payload text);"
                            "create table NotificationHandler(RecordId integer, PrimaryId text);")
            c.executemany("insert into NotificationHandler values (?,?)",
                          enumerate([ai.APP_ID, "QQ", "Weixin", "ThunderbirdToast", ai.APP_ID+"Tools"], start=1))
            def insert(i, handler, payload):
                c.execute("insert into Notification values (?,?,?,'toast',?)", (i,handler,FILETIME+10000000*i,payload))
            insert(1, 1, REPLY)
            c.commit()
            with patch.object(notify, "WPN_DB", str(path)):
                cursor, rows = self.s._poll_db(None)
                self.assertEqual((cursor, rows), (1, []))
                for i, handler in enumerate((2, 3, 4, 5, 1, 1), start=2):
                    insert(i, handler, "<toast><text>Sample</text></toast>")
                c.commit()
                cursor, rows = self.s._poll_db(cursor)
                self.s._on_rows(rows)
                self.s._on_rows(self.s._poll_db(cursor)[1])
            c.close()
        self.assertEqual(self.s.counts, {"qq":1,"wechat":1,"mail":1,ai.SHARED:2})
        self.assertEqual([e.get("sender") for e in self.seen], ["Sample","Sample",None,None,None])

    def test_flash_before_and_after_toast(self):
        self.s._on_ai_flash(100)
        self.s._on_ai_toast("codex", "任务完成", 100.2)
        self.s._on_ai_flash(101)
        self.s._on_ai_toast("codex", "任务完成", 101.2)
        self.assertFalse(self.s._ai_flash_timer.isActive())
        self.assertEqual(self.s.counts, {"codex":2})
        self.assertEqual(len(self.seen),2)

    def test_delayed_delivery_and_read_state(self):
        for when, clear in [(100, False), (120, True)]:
            self.s._on_ai_flash(when)
            self.s._ai_flash_timer.stop()
            self.s._flush_ai_flash()
            if clear:
                self.s.clear(ai.SHARED)
            self.s._on_ai_toast("chatgpt", "新消息", when + .2)
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.s.counts, {ai.SHARED:0,"chatgpt":1})
        self.assertEqual([r["kind"] for r in self.s.history], ["chatgpt","chatgpt"])

    def test_stop(self):
        self.s._on_ai_flash(100)
        self.s.stop()
        self.s._flush_ai_flash()
        self.s._on_rows([(1, ai.APP_ID, 1, "toast", "", ("codex","任务完成"))])
        self.assertEqual(self.seen, [])

    def test_page_and_four_themes(self):
        page = MessagesPage(SimpleNamespace(notify=self.s))
        page.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        page.setAutoFillBackground(True)
        page.resize(616, page.height if isinstance(page.height, int) else 362)
        page.show()
        self.s.counts_changed.connect(lambda _: page.refresh())
        for k in ("qq", "wechat", "mail"):
            self.s._emit({"kind":k,"name":{"qq":"QQ","wechat":"微信","mail":"邮件"}[k],
                          "time":time.time(),"source":"toast"})
        for k in ai.NAMES:
            self.s._on_ai_toast(k,"新消息",time.time())
        for mode in ("dark","light","rouge","sky"):
            theme.set_mode(mode)
            palette = page.palette()
            palette.setBrush(QtGui.QPalette.ColorRole.Window, theme.tint_brush(QtCore.QRectF(page.rect())))
            page.setPalette(palette)
            APP.processEvents()
            self.assertTrue(page.shared.isVisible())
            self.assertEqual(len(page.hist.rows),6)
            self.assertGreater(page.tiles["codex"].y(),page.tiles["qq"].y()+80)
            for tile in page.tiles.values():
                self.assertTrue(page.rect().contains(tile.geometry()))
                self.assertEqual(tile.count,1)
                self.assertRegex(tile.last,r"^\d\d:\d\d$")
            pix = page.grab()
            self.assertFalse(pix.isNull())
            if os.getenv("WISLAND_SCREENSHOTS"):
                pix.save(str(Path(os.environ["WISLAND_SCREENSHOTS"])/f"messages-{mode}.png"))
        compact = CompactView()
        compact.badges = self.s.counts.copy()
        image = QtGui.QImage(150,24,QtGui.QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QtGui.QPainter(image)
        self.assertEqual(compact._badges(painter, 100, 12, 1), 100-13*6)
        painter.end()
        page.shared.clicked.emit()
        self.assertTrue(page.shared.isHidden())
        self.s.open_ai_client = lambda: False
        page.tiles["codex"].clicked.emit()
        self.assertEqual(self.s.counts["codex"],1)
        self.s.open_ai_client = lambda: True
        page.tiles["codex"].clicked.emit()
        self.assertEqual(self.s.counts["codex"],0)
        self.assertEqual(self.s.counts["chatgpt"],1)
        page._clear_all()
        self.assertEqual(sum(self.s.counts.values()),0)
        self.assertEqual(len(page.hist.rows),6)
        page.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
