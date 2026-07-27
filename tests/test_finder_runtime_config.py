import os
import sys
import unittest
import urllib.parse

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import finder  # noqa: E402


class FinderRuntimeConfigTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("FINDER_CONTACT_EMAIL", None)

    def test_openalex_reads_contact_email_at_call_time(self):
        os.environ["FINDER_CONTACT_EMAIL"] = "researcher@example.com"
        captured = []
        original = finder._get_json

        def fake_get_json(url):
            captured.append(url)
            return {"results": []}

        finder._get_json = fake_get_json
        try:
            finder.openalex("sleep", 3)
        finally:
            finder._get_json = original

        query = urllib.parse.parse_qs(urllib.parse.urlparse(captured[0]).query)
        self.assertEqual(query["mailto"], ["researcher@example.com"])


if __name__ == "__main__":
    unittest.main()
