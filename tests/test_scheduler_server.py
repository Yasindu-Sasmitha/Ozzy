"""Integration checks for the Stage 9 wiring in server.py (no Gemini or Windows required)."""
import asyncio
import json
import os
import sys
import tempfile
import threading
import types as pytypes
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import memory_service
import scheduler_service as sched

# server.py imports Windows-only automation modules. Use stand-ins when they cannot load here.
_STUBBED = []
for _name in ("computer_control", "browser_control", "windows_automation", "windows_workflows",
              "safe_file_actions", "office_automation", "office_documents", "workflow_engine", "workflow_library"):
    try:
        __import__(_name)
    except Exception:
        stub = MagicMock(name=_name)
        stub.__name__ = _name
        sys.modules[_name] = stub
        _STUBBED.append(_name)

os.environ.setdefault("OZZY_DATA_DIR", tempfile.mkdtemp(prefix="ozzy-server-test-"))
try:
    import server
    SERVER_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - reported by the skip reason
    server = None
    SERVER_IMPORT_ERROR = exc
finally:
    # Do not leak stand-ins into other test modules; server.py keeps its own references.
    for _name in _STUBBED:
        sys.modules.pop(_name, None)


@unittest.skipIf(server is None, f"server.py could not be imported here: {SERVER_IMPORT_ERROR}")
class ServerSchedulerWiringTests(unittest.TestCase):
    def test_live_config_validates_with_real_sdk_and_has_clock(self):
        from google.genai import types
        config = server.make_live_config()
        text = config["system_instruction"]["parts"][0]["text"]
        self.assertIn("CURRENT CLOCK", text)
        self.assertIn("STAGE 9", text)
        self.assertIn("PERSONALITY", text)
        validated = types.LiveConnectConfig.model_validate(config)
        self.assertTrue(validated.tools)
        # The static config stays available and unchanged for other code.
        self.assertNotIn("CURRENT CLOCK", server.LIVE_CONFIG["system_instruction"]["parts"][0]["text"])

    def test_scheduler_tool_declarations_match_tool_names_and_are_unique(self):
        declared = [d.name for tool in server.SCHEDULER_TOOLS for d in tool.function_declarations]
        self.assertEqual(set(declared), sched.TOOL_NAMES)
        all_names = [d.name for tool in server.LIVE_CONFIG["tools"] for d in tool.function_declarations]
        self.assertEqual(len(all_names), len(set(all_names)), "duplicate tool names in the Live config")

    def test_scheduled_turn_allowlist_only_names_real_tools(self):
        all_names = {d.name for tool in server.LIVE_CONFIG["tools"] for d in tool.function_declarations}
        self.assertTrue(sched.SCHEDULED_TURN_ALLOWED_TOOLS <= all_names)
        self.assertFalse(sched.SCHEDULED_TURN_ALLOWED_TOOLS & (server.PC_CONTROL_TOOL_NAMES | server.BROWSER_CONTROL_TOOL_NAMES))

    def test_session_handle_delivers_prompt_and_pushes_toast(self):
        async def scenario():
            sent = []

            class Socket:
                async def send(self, message):
                    sent.append(json.loads(message))

            queue = asyncio.Queue()
            handle = server.SessionHandle(Socket(), queue, lambda: 0)
            event = {"id": 7, "title": "Stretch", "note": "", "kind": "reminder", "due_local": "today 4:30 PM"}
            await handle.notify(event)
            await handle.deliver(event)
            kind, payload = queue.get_nowait()
            return sent, kind, payload, handle

        sent, kind, payload, handle = asyncio.run(scenario())
        self.assertEqual(sent[0]["type"], "reminder_due")
        self.assertEqual(sent[0]["event"]["id"], 7)
        self.assertEqual(kind, "text")
        self.assertIn("[OZZY SCHEDULER", payload)
        self.assertFalse(handle.activity.tool_allowed("type_text"))


@unittest.skipIf(server is None, f"server.py could not be imported here: {SERVER_IMPORT_ERROR}")
class ReminderHttpApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "t.sqlite3"
        self.patch = patch.object(memory_service, "database_path", return_value=self.db)
        self.patch.start()
        memory_service.initialize()
        sched.initialize()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), lambda *a, **k: server.OzzyRequestHandler(*a, directory=self.temp.name, **k))
        self.port = self.httpd.server_address[1]
        self.port_patch = patch.object(server, "HTTP_PORT", self.port)
        self.port_patch.start()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.port_patch.stop()
        self.patch.stop()
        self.temp.cleanup()

    def call(self, method, path, body=None, headers=None):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None),
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    TRUSTED = {"X-Ozzy-Request": "1"}

    def test_post_requires_ozzy_header_and_local_origin(self):
        self.assertEqual(self.call("POST", "/api/reminders/settings", {"speak_first": False})[0], 403)
        status, _ = self.call("POST", "/api/reminders/settings", {"speak_first": False},
                              {**self.TRUSTED, "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertTrue(sched.get_settings()["speak_first"])
        status, data = self.call("POST", "/api/reminders/settings", {"speak_first": False}, self.TRUSTED)
        self.assertEqual(status, 200)
        self.assertFalse(data["settings"]["speak_first"])

    def test_event_lifecycle_over_http(self):
        sched.create_reminder("Stretch", in_minutes=0.01)
        import time as _time
        _time.sleep(0.9)
        with patch.object(sched, "now", lambda: _time.time() + 5):
            sched.claim_due()
            status, data = self.call("GET", "/api/reminders/events")
            self.assertEqual(status, 200)
            event = data["events"][0]
            self.assertEqual(event["title"], "Stretch")
            self.assertEqual(self.call("POST", f"/api/reminders/events/{event['id']}/speech", None, self.TRUSTED)[1]["granted"], True)
            self.assertEqual(self.call("POST", f"/api/reminders/events/{event['id']}/speech", None, self.TRUSTED)[1]["granted"], False)
            self.assertTrue(self.call("POST", f"/api/reminders/events/{event['id']}/shown", None, self.TRUSTED)[1]["ok"])
            self.assertEqual(self.call("GET", "/api/reminders/events")[1]["events"], [])

    def test_list_and_cancel_over_http(self):
        created = sched.create_reminder("Later", in_minutes=30)
        status, data = self.call("GET", "/api/reminders")
        self.assertEqual(status, 200)
        self.assertEqual(data["reminders"][0]["id"], created["id"])
        self.assertIn("time_12h", data["now"])
        self.assertTrue(self.call("POST", f"/api/reminders/{created['id']}/cancel", None, self.TRUSTED)[1]["ok"])
        self.assertEqual(self.call("GET", "/api/reminders")[1]["reminders"], [])

    def test_bad_snooze_is_a_400(self):
        sched.create_reminder("A", in_minutes=0.01)
        import time as _time
        with patch.object(sched, "now", lambda: _time.time() + 120):
            event = sched.claim_due()[0]
        status, _ = self.call("POST", f"/api/reminders/events/{event['id']}/snooze", {"minutes": 0}, self.TRUSTED)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
