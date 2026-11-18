import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        f"solar_{name}", ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logger = load("logger")
notify = load("notify")


class SplitMessageTest(unittest.TestCase):
    def test_short_message_is_one_part(self):
        self.assertEqual(notify.split_message("hello", 10), ["hello"])

    def test_long_paragraph_is_hard_wrapped(self):
        self.assertEqual(
            notify.split_message("x" * 25, 10), ["x" * 10, "x" * 10, "x" * 5]
        )

    def test_paragraphs_pack_greedily(self):
        self.assertEqual(
            notify.split_message("aaaa\n\nbbbb\n\ncccccccccccc", 10),
            ["aaaa\n\nbbbb", "cccccccccc", "cc"],
        )

    def test_emoji_are_split_by_utf16_units(self):
        parts = notify.split_message("😀" * 5, 9)
        self.assertEqual(parts, ["😀" * 4, "😀"])
        self.assertLessEqual(max(notify.utf16_units(part) for part in parts), 9)


class LoggerTest(unittest.TestCase):
    def record(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run-1"
            run_dir.mkdir()
            meta = {
                "id": "run-1",
                "task": "q",
                "source": "cli",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            (run_dir / "meta.json").write_text(json.dumps(meta))
            for name, value in files.items():
                (run_dir / name).write_text(json.dumps(value))
            return logger.build_record(run_dir)

    def test_approved_run_is_complete(self):
        record = self.record(
            {
                "research.json": {"status": "complete", "findings": []},
                "draft.json": {"status": "complete", "draft": "reply"},
                "review.json": {"status": "complete", "verdict": "approved", "issues": []},
            }
        )
        self.assertEqual(
            (record["status"], record["verdict"], record["draft"]),
            ("complete", "approved", "reply"),
        )

    def test_partial_stage_makes_run_partial(self):
        record = self.record(
            {
                "research.json": {"status": "partial", "findings": []},
                "draft.json": {"status": "complete", "draft": "reply"},
                "review.json": {"status": "complete", "verdict": "approved", "issues": []},
            }
        )
        self.assertEqual(record["status"], "partial")

    def test_missing_draft_is_failed_unless_clarification(self):
        self.assertEqual(
            self.record({"research.json": {"status": "complete", "findings": []}})[
                "status"
            ],
            "failed",
        )
        self.assertEqual(
            self.record(
                {"research.json": {"status": "needs_clarification", "findings": []}}
            )["status"],
            "needs_clarification",
        )

    def test_missing_checker_is_failed(self):
        record = self.record(
            {
                "research.json": {"status": "complete", "findings": []},
                "draft.json": {"status": "complete", "draft": "reply"},
            }
        )
        self.assertEqual(record["status"], "failed")

    def test_invalid_artifact_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.record(
                {
                    "research.json": {"status": "complete", "findings": []},
                    "draft.json": {"status": "complete", "draft": 1},
                }
            )


class MessageTest(unittest.TestCase):
    def test_issues_are_included(self):
        message = notify.build_message(
            {
                "id": "r1",
                "status": "complete",
                "verdict": "needs_changes",
                "task": "q",
                "draft": "d",
                "issues": [
                    {
                        "problem": "unsupported price",
                        "location": "prices",
                        "suggestion": "cite the researcher's finding",
                    }
                ],
            }
        )
        self.assertIn("unsupported price", message)
        self.assertIn("prices", message)


class Response:
    def __init__(self, payload=b'{"ok": true, "result": {"message_id": 1}}'):
        self.payload = payload
        self.status = 200

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RetryTest(unittest.TestCase):
    def send(self, responses, waits):
        calls = []

        def fake_open_url(request):
            calls.append(request.full_url)
            item = responses[len(calls) - 1]
            if isinstance(item, Exception):
                raise item
            return item

        with (
            mock.patch.object(notify, "open_url", fake_open_url),
            mock.patch.object(notify.time, "sleep", waits.append),
        ):
            notify.send_part("https://example.test/botTOKEN/sendMessage", "1", "hi", "TOKEN")
        return calls

    def test_429_waits_for_retry_after(self):
        error = urllib.error.HTTPError(
            "https://example.test",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"ok": false, "parameters": {"retry_after": 3}}'),
        )
        waits = []
        calls = self.send([error, Response()], waits)
        self.assertEqual(len(calls), 2)
        self.assertEqual(waits, [3])

    def test_retry_after_beyond_budget_is_reported(self):
        error = urllib.error.HTTPError(
            "https://example.test",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(b'{"ok": false, "parameters": {"retry_after": 60}}'),
        )
        with self.assertRaises(RuntimeError) as caught:
            self.send([error], [])
        self.assertIn("retry after 60s", str(caught.exception))

    def test_not_ok_response_is_retried(self):
        calls = self.send(
            [Response(b'{"ok": false, "description": "chat not found"}'), Response()], []
        )
        self.assertEqual(len(calls), 2)


class NotifySkipTest(unittest.TestCase):
    def test_failed_run_is_skipped_without_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp) / "run.json"
            run_path.write_text(json.dumps({"id": "r", "status": "failed", "draft": "x"}))
            with (
                mock.patch.object(sys, "argv", ["notify.py", "--run-dir", tmp]),
                mock.patch.dict(
                    os.environ,
                    {
                        "DRY_RUN": "false",
                        "TELEGRAM_BOT_TOKEN": "t",
                        "TELEGRAM_CHAT_ID": "1",
                    },
                ),
                mock.patch.object(
                    notify,
                    "open_url",
                    side_effect=AssertionError("must not send"),
                ),
            ):
                self.assertEqual(notify.main(), 0)
            delivery = json.loads(run_path.read_text(encoding="utf-8"))["delivery"]
            self.assertTrue(delivery["skipped"])
            self.assertFalse(delivery["delivered"])


class EndpointTest(unittest.TestCase):
    def run_notifier(self, endpoint):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp) / "run.json"
            run_path.write_text(
                json.dumps({"id": "r", "status": "complete", "draft": "d"})
            )
            env = {
                "DRY_RUN": "false",
                "TELEGRAM_BOT_TOKEN": "t",
                "TELEGRAM_CHAT_ID": "1",
                "SOLAR_TELEGRAM_ENDPOINT": endpoint,
            }
            with (
                mock.patch.object(sys, "argv", ["notify.py", "--run-dir", tmp]),
                mock.patch.dict(os.environ, env),
                mock.patch.object(
                    notify, "open_url", side_effect=AssertionError("must not send")
                ),
            ):
                code = notify.main()
            return code, json.loads(run_path.read_text(encoding="utf-8"))["delivery"]

    def test_http_network_endpoint_is_rejected(self):
        code, delivery = self.run_notifier("http://example.test/send")
        self.assertEqual(code, 1)
        self.assertFalse(delivery["delivered"])
        self.assertNotIn("example.test", delivery["error"])

    def test_endpoint_without_scheme_is_rejected(self):
        code, delivery = self.run_notifier("example.test/send")
        self.assertEqual(code, 1)
        self.assertIn("scheme", delivery["error"])


if __name__ == "__main__":
    unittest.main()
