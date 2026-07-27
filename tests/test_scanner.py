import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)
FIX = os.path.join(os.path.dirname(__file__), "fixtures")

import scanner  # noqa: E402


def _fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


class ParserTest(unittest.TestCase):
    def test_ddg_html(self):
        rows = scanner.parse_ddg_html(_fx("ddg_html.html"), limit=6)
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(r["url"].startswith("http") for r in rows))
        self.assertNotIn("duckduckgo.com/l/", rows[0]["url"])   # redirect decoded
        self.assertTrue(rows[0]["title"])

    def test_ddg_lite(self):
        html = """
        <table>
          <tr>
            <td><a rel="nofollow" href="https://example.com/one">First result</a></td>
          </tr>
          <tr><td class="result-snippet">A useful first snippet.</td></tr>
          <tr>
            <td><a rel="nofollow" href="https://example.org/two">Second result</a></td>
          </tr>
          <tr><td class="result-snippet">Another useful snippet.</td></tr>
        </table>
        """
        rows = scanner.parse_ddg_lite(html, limit=6)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "First result")
        self.assertEqual(rows[0]["url"], "https://example.com/one")
        self.assertEqual(rows[0]["snippet"], "A useful first snippet.")

    def test_bing(self):
        rows = scanner.parse_bing(_fx("bing.html"), limit=6)
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(r["url"].startswith("http") for r in rows))
        self.assertTrue(all("bing.com" not in r["url"] for r in rows))  # ck/a decoded

    def test_news_rss(self):
        rows = scanner.parse_news_rss(_fx("news_rss.xml"), limit=5)
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(r["url"].startswith("http") for r in rows))
        self.assertTrue(rows[0]["title"])

    def test_wikipedia(self):
        row = scanner.parse_wikipedia(_fx("wiki_search.json"))
        self.assertIsNotNone(row)
        self.assertIn("Caffeine", row["title"])
        self.assertIn("wikipedia.org/wiki/", row["url"])
        self.assertTrue(row["snippet"])


class WebSearchFallbackTest(unittest.TestCase):
    def test_falls_through_ddg_html_to_ddg_lite_before_bing(self):
        calls = []
        lite = """
        <a rel="nofollow" href="https://example.com/lite">Lite result</a>
        <td class="result-snippet">Found by the lite endpoint.</td>
        """

        def fetch_html(url):
            calls.append(url)
            if "html.duckduckgo" in url:
                return "<html>no results</html>"
            if "lite.duckduckgo" in url:
                return lite
            raise AssertionError("Bing should not be reached")

        rows, engine = scanner.web_search("caffeine sleep", fetch_html, limit=5)
        self.assertEqual(engine, "duckduckgo-lite")
        self.assertEqual(rows[0]["url"], "https://example.com/lite")
        self.assertEqual(len(calls), 2)

    def test_falls_through_to_bing_when_ddg_empty(self):
        calls = []

        def fetch_html(url):
            calls.append(url)
            if "duckduckgo" in url:
                return "<html>no results here</html>"   # DDG yields nothing
            if "bing.com" in url:
                return _fx("bing.html")
            raise AssertionError("unexpected url " + url)

        rows, engine = scanner.web_search("caffeine sleep", fetch_html, limit=5)
        self.assertEqual(engine, "bing")
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(len(calls), 3)  # DDG HTML, DDG Lite, then Bing

    def test_uses_ddg_when_it_works(self):
        def fetch_html(url):
            return _fx("ddg_html.html") if "duckduckgo" in url else ""
        rows, engine = scanner.web_search("x", fetch_html, limit=5)
        self.assertEqual(engine, "duckduckgo")
        self.assertGreaterEqual(len(rows), 3)

    def test_all_fail_returns_empty(self):
        def fetch_html(url):
            raise RuntimeError("network down")
        rows, engine = scanner.web_search("x", fetch_html)
        self.assertEqual(rows, [])
        self.assertIn("none", engine)


if __name__ == "__main__":
    unittest.main()
