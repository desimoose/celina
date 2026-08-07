import io
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import paths  # noqa: E402
import update_check  # noqa: E402


def _response(payload):
    body = json.dumps(payload).encode("utf-8")
    cm = mock.MagicMock()
    cm.__enter__.return_value = io.BytesIO(body)
    cm.__exit__.return_value = False
    return cm


class UpdateCheckTest(unittest.TestCase):
    def setUp(self):
        self._version = paths.APP_VERSION
        self._repo = paths.GITHUB_REPO
        paths.APP_VERSION = "1.2.0"
        paths.GITHUB_REPO = "example/celina"

    def tearDown(self):
        paths.APP_VERSION = self._version
        paths.GITHUB_REPO = self._repo

    @mock.patch("update_check.urllib.request.urlopen")
    def test_newer_release_reports_update_available(self, urlopen):
        urlopen.return_value = _response({"tag_name": "v1.3.0"})

        result = update_check.check()

        self.assertEqual(result, {
            "current": "1.2.0",
            "latest": "1.3.0",
            "update_available": True,
            "url": "https://github.com/example/celina/releases/latest",
        })

    @mock.patch("update_check.urllib.request.urlopen")
    def test_same_or_older_release_reports_no_update(self, urlopen):
        urlopen.return_value = _response({"tag_name": "v1.2.0"})

        result = update_check.check()

        self.assertFalse(result["update_available"])
        self.assertEqual(result["latest"], "1.2.0")

    @mock.patch("update_check.urllib.request.urlopen")
    def test_leading_v_is_stripped_for_comparison(self, urlopen):
        urlopen.return_value = _response({"tag_name": "V1.10.0"})

        result = update_check.check()

        self.assertEqual(result["latest"], "1.10.0")
        self.assertTrue(result["update_available"])

    @mock.patch(
        "update_check.urllib.request.urlopen",
        side_effect=urllib.error.URLError("offline"),
    )
    def test_network_failure_is_silent_not_raised(self, _urlopen):
        result = update_check.check()

        self.assertIsNone(result["latest"])
        self.assertFalse(result["update_available"])
        self.assertEqual(result["current"], "1.2.0")

    @mock.patch("update_check.urllib.request.urlopen", side_effect=TimeoutError())
    def test_timeout_is_silent_not_raised(self, _urlopen):
        result = update_check.check()

        self.assertFalse(result["update_available"])

    @mock.patch("update_check.urllib.request.urlopen")
    def test_malformed_response_is_silent_not_raised(self, urlopen):
        cm = mock.MagicMock()
        cm.__enter__.return_value = io.BytesIO(b"not json")
        cm.__exit__.return_value = False
        urlopen.return_value = cm

        result = update_check.check()

        self.assertFalse(result["update_available"])
        self.assertIsNone(result["latest"])

    @mock.patch("update_check.urllib.request.urlopen")
    def test_non_dotted_tag_falls_back_to_inequality(self, urlopen):
        urlopen.return_value = _response({"tag_name": "nightly"})

        result = update_check.check()

        self.assertEqual(result["latest"], "nightly")
        self.assertTrue(result["update_available"])  # differs from "1.2.0"


if __name__ == "__main__":
    unittest.main()
