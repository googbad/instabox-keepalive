import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import instabox_actions as controller


class ParseTimeTests(unittest.TestCase):
    def test_zulu_time(self):
        value = controller.parse_time("2026-11-03T00:00:00Z")
        self.assertEqual(value.tzinfo, timezone.utc)

    def test_invalid_time(self):
        self.assertIsNone(controller.parse_time("not-a-date"))


class ApiRequestTests(unittest.TestCase):
    @patch("instabox_actions.urllib.request.urlopen")
    def test_lifecycle_has_idempotency_key(self, mocked_open):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"state":"suspended"}'
        mocked_open.return_value = response
        with patch.object(controller, "API_KEY", "dummy-test-key"):
            controller.api_request("POST", "/v1/machines/m1/suspend")
        request = mocked_open.call_args.args[0]
        self.assertTrue(request.get_header("Idempotency-key"))

    @patch("instabox_actions.urllib.request.urlopen")
    def test_exec_does_not_need_idempotency_key(self, mocked_open):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"exitCode":0}'
        mocked_open.return_value = response
        with patch.object(controller, "API_KEY", "dummy-test-key"):
            controller.api_request("POST", "/v1/machines/m1/exec", {"cmd":"date"})
        request = mocked_open.call_args.args[0]
        self.assertIsNone(request.get_header("Idempotency-key"))


class BarkTests(unittest.TestCase):
    @patch("instabox_actions.urllib.request.urlopen")
    def test_bark_payload_and_group(self, mocked_open):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":200}'
        mocked_open.return_value = response
        with patch.dict(os.environ, {"BARK_URL": "https://bark.example/device-key/"}):
            self.assertTrue(controller.send_bark("title", "body"))
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.full_url, "https://bark.example/device-key")
        self.assertEqual(
            json.loads(request.data.decode()),
            {"title":"title", "body":"body", "group":"InstaBox"},
        )

    @patch("instabox_actions.urllib.request.urlopen")
    def test_bark_missing_secret_skips_request(self, mocked_open):
        with patch.dict(os.environ, {"BARK_URL": ""}):
            with redirect_stdout(StringIO()) as output:
                self.assertFalse(controller.send_bark("title", "body"))
        mocked_open.assert_not_called()
        self.assertIn("BARK_URL is not configured", output.getvalue())


class RotationTests(unittest.TestCase):
    @patch.object(controller, "send_bark", return_value=True)
    @patch.object(controller, "fetch_machine")
    @patch.object(controller, "wait_for_state")
    @patch.object(controller, "api_request")
    def test_rotation_order_and_run_started_refresh(
        self, api, wait, fetch, bark
    ):
        before = "2026-11-03T00:00:00Z"
        after = "2026-11-03T07:31:00Z"
        wait.side_effect = [
            {"state":"suspended"},
            {"state":"running", "runStartedAt":after},
        ]
        controller.perform_rotation({
            "id":"m1", "name":"test-machine", "runStartedAt":before
        })
        self.assertEqual(
            [call.args[1] for call in api.call_args_list],
            ["/v1/machines/m1/suspend", "/v1/machines/m1/resume"],
        )
        bark.assert_called_once()

    @patch.object(controller, "send_bark", return_value=True)
    @patch.object(controller, "fetch_machine")
    @patch.object(controller, "wait_for_state")
    @patch.object(controller, "api_request")
    def test_rotation_refuses_missing_run_started_at(
        self, api, wait, fetch, bark
    ):
        with self.assertRaises(controller.InstaBoxError):
            controller.perform_rotation({
                "id":"m1", "name":"test-machine", "runStartedAt":None
            })
        api.assert_not_called()
        bark.assert_not_called()


class RecoveryTests(unittest.TestCase):
    @patch.object(controller, "send_bark", return_value=True)
    @patch.object(controller, "wait_for_state")
    @patch.object(controller, "api_request")
    def test_resumes_suspended_machine_and_notifies(self, api, wait, bark):
        wait.return_value = {
            "state":"running",
            "runStartedAt":"2026-11-03T07:40:00Z",
        }
        controller.recover_suspended({
            "id":"m1",
            "name":"test-machine",
            "state":"suspended",
            "runStartedAt":"2026-11-03T00:00:00Z",
        })
        api.assert_called_once_with("POST", "/v1/machines/m1/resume")
        bark.assert_called_once()

    @patch.object(controller, "send_bark")
    @patch.object(controller, "api_request")
    def test_waits_during_active_cooldown(self, api, bark):
        from datetime import timedelta
        future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        controller.recover_suspended({
            "id":"m1",
            "name":"test-machine",
            "state":"suspended",
            "cooldownUntil":future,
        })
        api.assert_not_called()
        bark.assert_not_called()


if __name__ == "__main__":
    unittest.main()
