import unittest
from datetime import datetime, timezone, timedelta

from scripts.status_monitor import duration_text, parse_time, summarize


class StatusMonitorTests(unittest.TestCase):
    def test_parse_z_time(self):
        self.assertEqual(parse_time("2026-11-03T00:00:00Z").tzinfo, timezone.utc)

    def test_bad_time(self):
        self.assertIsNone(parse_time("not-a-time"))

    def test_duration(self):
        self.assertEqual(duration_text(3661), "1h 1m")

    def test_running_summary(self):
        now = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
        started = (now - timedelta(minutes=90)).isoformat()
        item = summarize({
            "id": "m1", "name": "muse", "state": "running",
            "runStartedAt": started, "runtime": {"ready": True},
            "storage": {"synced": True}, "free": True,
        }, now)
        self.assertEqual(item["elapsed"], "1h 30m")
        self.assertEqual(item["maxRunRemaining"], "6h 30m")
        self.assertTrue(item["ready"])
        self.assertTrue(item["persistentStorageSynced"])

    def test_suspended_has_no_runtime_remaining(self):
        item = summarize({"id": "m1", "state": "suspended"}, datetime.now(timezone.utc))
        self.assertIsNone(item["elapsed"])
        self.assertIsNone(item["maxRunRemaining"])


if __name__ == "__main__":
    unittest.main()
