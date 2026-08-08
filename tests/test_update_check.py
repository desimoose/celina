import os
import sys
import unittest
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import paths  # noqa: E402
import update_check  # noqa: E402


class UpdateCheckTest(unittest.TestCase):
    def setUp(self):
        self._version = paths.APP_VERSION
        paths.APP_VERSION = "1.2.0"

    def tearDown(self):
        paths.APP_VERSION = self._version

    @mock.patch("urllib.request.urlopen")
    def test_reports_local_only_version_status(self, _urlopen):
        self.assertEqual(update_check.check(), {
            "current": "1.2.0",
            "status": "local-only",
            "remote_check": False,
        })

    @mock.patch("urllib.request.urlopen")
    def test_never_makes_an_external_request(self, urlopen):
        update_check.check()

        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
