import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import bark_notify


class BarkNotifyTests(unittest.TestCase):
    @patch("bark_notify.urllib.request.urlopen")
    def test_posts_expected_payload_and_accepts_code_200(self, mocked_open):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":200}'
        mocked_open.return_value = response

        self.assertTrue(bark_notify.send_bark(
            "InstaBox resumed",
            "Machine is running again.",
            url="https://bark.example/device-key/",
        ))

        request = mocked_open.call_args.args[0]
        self.assertEqual(request.full_url, "https://bark.example/device-key")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "title": "InstaBox resumed",
                "body": "Machine is running again.",
                "group": "InstaBox",
            },
        )

    @patch("bark_notify.urllib.request.urlopen")
    def test_non_200_bark_code_is_failure(self, mocked_open):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":400}'
        mocked_open.return_value = response
        self.assertFalse(bark_notify.send_bark("title", "body", url="https://bark.example/key"))

    @patch.dict(os.environ, {"BARK_URL": ""})
    @patch("bark_notify.urllib.request.urlopen")
    def test_missing_secret_skips_network(self, mocked_open):
        self.assertFalse(bark_notify.send_bark("title", "body"))
        mocked_open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
