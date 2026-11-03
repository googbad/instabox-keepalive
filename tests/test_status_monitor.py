
import unittest
from datetime import datetime, timezone, timedelta

from scripts.status_monitor import (
    parse_time,
    format_duration,
    summarize_machine,
)


class StatusMonitorTests(unittest.TestCase):

    def test_parse_z_time(self):
        self.assertEqual(
            parse_time("2026-11-03T00:00:00Z").tzinfo,
            timezone.utc,
        )

    def test_bad_time(self):
        self.assertIsNone(parse_time("not-a-time"))

    def test_duration(self):
        self.assertEqual(format_duration(3661), "1h 1m 1s")

    def test_running_summary(self):
        started = (
            datetime.now(timezone.utc) - timedelta(minutes=90)
        ).isoformat()

        item = summarize_machine({
            "id": "m1",
            "name": "muse",
            "state": "running",
            "runStartedAt": started,
            "maxRunMinutes": 480,
            "runtime": {"ready": True},
            "storage": {"synced": True},
            "free": True,
        })

        self.assertGreaterEqual(item["elapsedSeconds"], 5400)
        self.assertLess(item["elapsedSeconds"], 5410)
        self.assertEqual(item["maxRunMinutes"], 480)
        self.assertTrue(item["runtimeReady"])
        self.assertTrue(item["storageSynced"])
        self.assertFalse(item["warning470"])

    def test_470_minute_warning(self):
        started = (
            datetime.now(timezone.utc) - timedelta(minutes=472)
        ).isoformat()

        item = summarize_machine({
            "id": "m1",
            "name": "muse",
            "state": "running",
            "runStartedAt": started,
            "maxRunMinutes": 480,
        })

        self.assertTrue(item["warning470"])
        self.assertLessEqual(item["maxRunRemainingSeconds"], 480)

    def test_suspended_has_no_runtime(self):
        item = summarize_machine({
            "id": "m1",
            "name": "muse",
            "state": "suspended",
        })

        self.assertIsNone(item["elapsedSeconds"])
        self.assertIsNone(item["maxRunRemainingSeconds"])
        self.assertFalse(item["warning470"])


if __name__ == "__main__":
    unittest.main()
