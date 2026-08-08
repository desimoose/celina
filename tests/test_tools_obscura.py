import os
import sys
import tempfile
import unittest
import urllib.parse
import subprocess
from unittest import mock

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import redaction  # noqa: E402
import sessions  # noqa: E402
import paths  # noqa: E402
import traffic  # noqa: E402
import tools  # noqa: E402


class FindObscuraTest(unittest.TestCase):
    def test_finds_binary_in_data_dir_vendor(self):
        tmp = os.path.join(
            os.environ.get("TEMP", "/tmp"), "celina_obscura_test"
        )
        os.environ["CELINA_HOME"] = tmp
        try:
            vend = os.path.join(paths.vendor_dir(), "obscura")
            os.makedirs(vend, exist_ok=True)
            fake = os.path.join(vend, "obscura.exe")
            with open(fake, "w", encoding="utf-8") as fh:
                fh.write("stub")
            found = tools.find_obscura()
            self.assertEqual(
                os.path.realpath(found), os.path.realpath(fake)
            )
        finally:
            os.environ.pop("CELINA_HOME", None)


class ObscuraTrafficTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = sessions.SessionStore(self.temp.name)
        self.session = self.store.create()
        self.recorder = traffic.TrafficRecorder(self.store)
        self.secret = "obscura-canary-secret-551"
        self.context = traffic.TrafficContext(
            session_id=self.session.session_id,
            run_id="run-1",
            correlation_id="correlation-1",
            recorder=self.recorder,
            redactor=redaction.Redactor([self.secret]),
        )

    def tearDown(self):
        self.temp.cleanup()

    @mock.patch("tools.find_obscura", return_value=r"C:\vendor\obscura.exe")
    @mock.patch("tools.subprocess.run")
    def test_dump_records_safe_process_metadata_and_redacted_output(
        self,
        run,
        _find,
    ):
        run.return_value = mock.Mock(
            returncode=0,
            stdout=f"<html>{self.secret}</html>".encode(),
            stderr=b"",
        )

        output = tools.obscura_dump(
            f"https://example.test/page?token={self.secret}",
            traffic_context=self.context,
        )

        self.assertIn(self.secret, output)
        record = self.recorder.list(self.session.session_id)[0]
        self.assertEqual(record.transport, "process")
        self.assertEqual(record.method_or_action, "page.fetch")
        self.assertEqual(record.status, 0)
        self.assertIn("[REDACTED]", urllib.parse.unquote(record.destination))
        self.assertIn(b"[REDACTED]", record.response_body)
        self.assertNotIn(b"C:\\vendor\\obscura.exe", record.request_body)
        self.assertNotIn(self.secret.encode(), record.request_body)

    @mock.patch("tools.find_obscura", return_value=r"C:\vendor\obscura.exe")
    @mock.patch("tools.subprocess.run")
    def test_dump_records_nonzero_exit_before_raising(self, run, _find):
        run.return_value = mock.Mock(
            returncode=7,
            stdout=b"",
            stderr=f"failed with {self.secret}".encode(),
        )

        with self.assertRaises(RuntimeError):
            tools.obscura_dump(
                "https://example.test/page",
                traffic_context=self.context,
            )

        record = self.recorder.list(self.session.session_id)[0]
        self.assertEqual(record.status, 7)
        self.assertEqual(record.error_class, "ProcessError")
        self.assertNotIn(self.secret, record.error_summary)
        self.assertIn(b"[REDACTED]", record.response_body)

    @mock.patch("tools.find_obscura", return_value=r"C:\vendor\obscura.exe")
    @mock.patch("tools.subprocess.run")
    def test_dump_records_timeout_before_raising(self, run, _find):
        run.side_effect = subprocess.TimeoutExpired(
            cmd="obscura",
            timeout=1,
            stderr=f"waited for {self.secret}".encode(),
        )

        with self.assertRaises(subprocess.TimeoutExpired):
            tools.obscura_dump(
                "https://example.test/page",
                timeout=1,
                traffic_context=self.context,
            )

        record = self.recorder.list(self.session.session_id)[0]
        self.assertIsNone(record.status)
        self.assertEqual(record.error_class, "ProcessError")
        self.assertNotIn(self.secret, record.error_summary)

    @mock.patch("tools.pdf.extract_text", return_value=("Readable PDF text.", "stdlib"))
    @mock.patch("tools.subprocess.run")
    def test_pdf_read_records_the_successful_process(self, run, extract_text):
        pdf_bytes = b"%PDF-1.7\n" + self.secret.encode()
        run.return_value = mock.Mock(
            returncode=0,
            stdout=pdf_bytes,
            stderr=b"",
        )

        text, backend = tools._fetch_obscura_pdf(
            r"C:\vendor\obscura.exe",
            f"https://example.test/source.pdf?token={self.secret}",
            traffic_context=self.context,
        )

        self.assertEqual((text, backend), ("Readable PDF text.", "stdlib"))
        records = self.recorder.list(self.session.session_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.transport, "process")
        self.assertEqual(record.method_or_action, "page.fetch")
        self.assertEqual(record.status, 0)
        self.assertIn("[REDACTED]", urllib.parse.unquote(record.destination))
        self.assertIn(b"[REDACTED]", record.response_body)
        extract_text.assert_called_once_with(pdf_bytes)

    @mock.patch("tools.subprocess.run")
    def test_pdf_read_records_nonzero_exit_before_raising(self, run):
        run.return_value = mock.Mock(
            returncode=9,
            stdout=b"",
            stderr=f"failed with {self.secret}".encode(),
        )

        with self.assertRaises(RuntimeError):
            tools._fetch_obscura_pdf(
                r"C:\vendor\obscura.exe",
                "https://example.test/source.pdf",
                traffic_context=self.context,
            )

        records = self.recorder.list(self.session.session_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.status, 9)
        self.assertEqual(record.error_class, "ProcessError")
        self.assertNotIn(self.secret, record.error_summary)
        self.assertIn(b"[REDACTED]", record.response_body)

    @mock.patch("tools.subprocess.run")
    def test_pdf_read_records_timeout_before_raising(self, run):
        run.side_effect = subprocess.TimeoutExpired(
            cmd="obscura",
            timeout=1,
            stderr=f"waited for {self.secret}".encode(),
        )

        with self.assertRaises(subprocess.TimeoutExpired):
            tools._fetch_obscura_pdf(
                r"C:\vendor\obscura.exe",
                "https://example.test/source.pdf",
                traffic_context=self.context,
            )

        records = self.recorder.list(self.session.session_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIsNone(record.status)
        self.assertEqual(record.error_class, "ProcessError")
        self.assertNotIn(self.secret, record.error_summary)
        self.assertIn(b"[REDACTED]", record.response_body)

    @mock.patch("tools.subprocess.run")
    def test_pdf_read_records_process_error_before_raising(self, run):
        run.side_effect = OSError(f"unable to launch with {self.secret}")

        with self.assertRaises(OSError):
            tools._fetch_obscura_pdf(
                r"C:\vendor\obscura.exe",
                "https://example.test/source.pdf",
                traffic_context=self.context,
            )

        records = self.recorder.list(self.session.session_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertIsNone(record.status)
        self.assertEqual(record.error_class, "ProcessError")
        self.assertNotIn(self.secret, record.error_summary)


class LooksLikePdfUrlTest(unittest.TestCase):
    def test_path_suffix_is_detected(self):
        self.assertTrue(tools._looks_like_pdf_url("https://x.test/paper.pdf"))

    def test_path_segment_is_detected(self):
        self.assertTrue(tools._looks_like_pdf_url("https://x.test/pdf/12345"))

    def test_pdf_query_key_is_detected(self):
        # EuropePMC and similar publishers signal a PDF-viewer page only
        # through a query key, e.g. https://europepmc.org/articles/PMC1?pdf=render
        self.assertTrue(
            tools._looks_like_pdf_url(
                "https://europepmc.org/articles/PMC13278887?pdf=render"
            )
        )

    def test_pdf_as_part_of_a_value_is_not_a_false_positive(self):
        # A "pdf" substring inside some unrelated query value should not
        # trip the heuristic - only a literal "pdf" query key does.
        self.assertFalse(
            tools._looks_like_pdf_url("https://x.test/article?ref=pdfsummary")
        )

    def test_ordinary_page_is_not_detected(self):
        self.assertFalse(tools._looks_like_pdf_url("https://x.test/article?id=1"))


class CapFetchedTextTest(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(tools._cap_fetched_text("short"), "short")

    def test_oversized_text_is_capped_with_a_visible_note(self):
        huge = "a" * (tools._MAX_FETCHED_TEXT_CHARS + 5000)

        capped = tools._cap_fetched_text(huge)

        self.assertLessEqual(
            len(capped), tools._MAX_FETCHED_TEXT_CHARS + len("\n\n[truncated for length]")
        )
        self.assertTrue(capped.endswith("[truncated for length]"))


class FetchAppliesTheTextCapTest(unittest.TestCase):
    @mock.patch(
        "tools.obscura_dump",
        return_value="word " * 200000,  # ~1M characters, like the real case
    )
    @mock.patch("tools.find_obscura", return_value=r"C:\vendor\obscura.exe")
    def test_obscura_stealth_text_dump_is_capped(self, _find, _dump):
        page = tools.fetch("https://example.test/pdf-viewer-page")

        self.assertEqual(page["engine"], "obscura")
        self.assertLessEqual(len(page["text"]), tools._MAX_FETCHED_TEXT_CHARS + 40)
        self.assertTrue(page["text"].endswith("[truncated for length]"))


class FetchPdfFallbackTest(unittest.TestCase):
    @mock.patch("tools._plain_page", return_value={
        "url": "https://example.test/document.pdf",
        "engine": "plain-pdf",
        "content_type": "application/pdf",
        "text": "Readable PDF evidence.",
    })
    @mock.patch("tools.obscura_dump", return_value="%PDF-1.7\nraw bytes")
    @mock.patch("tools._fetch_obscura_pdf_payload", side_effect=RuntimeError("unreadable"))
    @mock.patch("tools.find_obscura", return_value=r"C:\\vendor\\obscura.exe")
    def test_obscura_does_not_return_raw_pdf_bytes_as_page_text(
        self, _find, _pdf_fetch, _dump, plain_page
    ):
        page = tools.fetch("https://example.test/document.pdf")

        self.assertEqual(page["engine"], "plain-pdf")
        plain_page.assert_called_once()


if __name__ == "__main__":
    unittest.main()
