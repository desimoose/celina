import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock


SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)


SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class NotebooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = self.temp.name
        self.patch = mock.patch.dict(os.environ, {"CELINA_HOME": self.data_root})
        self.patch.start()
        import notebooks

        self.notebooks = importlib.reload(notebooks)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_create_notebook_rejects_empty_and_oversized_titles(self):
        with self.assertRaises(ValueError):
            self.notebooks.create_notebook("")
        with self.assertRaises(ValueError):
            self.notebooks.create_notebook("x" * 121)

    def test_create_notebook_returns_deterministic_ids(self):
        first = self.notebooks.create_notebook("Sleep research", goal="Understand REM")
        second = self.notebooks.create_notebook("Sleep research", goal="Different goal")
        self.assertEqual(first["id"], "sleep-research")
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["goal"], "Understand REM")
        self.assertEqual(
            self.notebooks.read_notebook(first["id"])["title"], "Sleep research"
        )

    def test_add_source_validates_required_fields_and_safe_ids(self):
        notebook = self.notebooks.create_notebook("Caffeine")
        with self.assertRaises(ValueError):
            self.notebooks.add_source(notebook["id"], {"excerpt": "No title"})
        with self.assertRaises(ValueError):
            self.notebooks.add_source(
                notebook["id"], {"title": "Too much", "excerpt": "x" * 5001}
            )

        source = self.notebooks.add_source(
            notebook["id"],
            {"title": "Journal article", "url": "https://example.com/study", "excerpt": "Findings"},
        )
        self.assertTrue(SAFE_ID.fullmatch(source["id"]))
        self.assertEqual(source["title"], "Journal article")
        self.assertEqual(source["url"], "https://example.com/study")

    def test_add_note_validates_and_orders_newest_first(self):
        notebook = self.notebooks.create_notebook("Field notes")
        first = self.notebooks.add_note(
            notebook["id"], {"title": "First note", "body": "Older note"}
        )
        second = self.notebooks.add_note(
            notebook["id"], {"title": "Second note", "body": "Newer note"}
        )

        self.assertTrue(SAFE_ID.fullmatch(first["id"]))
        self.assertTrue(SAFE_ID.fullmatch(second["id"]))
        notes = self.notebooks.read_notebook(notebook["id"])["notes"]
        self.assertEqual([note["title"] for note in notes], ["Second note", "First note"])

    def test_generate_learning_path_uses_goal_and_source_titles(self):
        notebook = self.notebooks.create_notebook("Sleep", goal="Learn better sleep")
        source = self.notebooks.add_source(
            notebook["id"],
            {"title": "Circadian rhythms", "excerpt": "Study the body clock."},
        )

        path = self.notebooks.generate_learning_path(notebook["id"], {})
        self.assertEqual([section["id"] for section in path["sections"]], [
            "foundations",
            "source-synthesis",
            "application-review",
        ])
        self.assertIn("Learn better sleep", json.dumps(path))
        self.assertIn("Circadian rhythms", json.dumps(path))
        self.assertIn(source["id"], json.dumps(path))

    def test_generate_learning_path_preserves_requested_depth(self):
        notebook = self.notebooks.create_notebook("Depth study")
        path = self.notebooks.generate_learning_path(notebook["id"], {"depth": "graduate"})
        self.assertEqual(path["depth"], "graduate")
        with self.assertRaisesRegex(ValueError, "depth"):
            self.notebooks.generate_learning_path(notebook["id"], {"depth": "expert"})

    def test_add_source_rejects_non_http_urls(self):
        notebook = self.notebooks.create_notebook("URL safety")
        with self.assertRaisesRegex(ValueError, "http or https"):
            self.notebooks.add_source(
                notebook["id"], {"title": "Unsafe", "url": "javascript:alert(1)", "excerpt": "Text"}
            )

    def test_add_source_preserves_search_capture_metadata(self):
        notebook = self.notebooks.create_notebook("Search captures")

        source = self.notebooks.add_source(
            notebook["id"],
            {
                "title": "Controlled trial",
                "url": "https://example.test/trial",
                "kind": "research",
                "excerpt": "Search excerpt:\nEvening caffeine delayed sleep onset.",
                "origin": "search",
                "source_result": {
                    "title": "Controlled trial",
                    "url": "https://example.test/trial",
                    "kind": "research",
                },
            },
        )

        self.assertEqual(source["origin"], "search")
        self.assertEqual(
            source["source_result"],
            {
                "title": "Controlled trial",
                "url": "https://example.test/trial",
                "kind": "research",
            },
        )

    def test_add_source_rejects_unsafe_search_result_urls(self):
        notebook = self.notebooks.create_notebook("Search capture URL safety")

        with self.assertRaisesRegex(ValueError, "http or https"):
            self.notebooks.add_source(
                notebook["id"],
                {
                    "title": "Unsafe result",
                    "url": "https://example.test/trial",
                    "excerpt": "Search excerpt:\nUnsafe source metadata.",
                    "origin": "search",
                    "source_result": {
                        "title": "Unsafe result",
                        "url": "javascript:alert(1)",
                        "kind": "research",
                    },
                },
            )

    def test_import_source_from_web_page_uses_document_citation_and_bounded_excerpt(self):
        notebook = self.notebooks.create_notebook("Import web")

        source = self.notebooks.import_source(
            notebook["id"],
            {"url": "https://example.com/article", "title": "Article import", "kind": "paper"},
            {
                "url": "https://example.com/article",
                "content_type": "text/html; charset=utf-8",
                "engine": "plain",
                "text": "A" * 9000,
            },
        )

        self.assertEqual(source["origin"], "import")
        self.assertEqual(source["content_type"], "text/html; charset=utf-8")
        self.assertEqual(source["engine"], "plain")
        self.assertLessEqual(len(source["excerpt"]), self.notebooks._EXCERPT_LIMIT)
        self.assertEqual(
            source["citations"],
            [
                {
                    "id": "source-1-doc",
                    "label": "document",
                    "text": "A" * self.notebooks._IMPORT_CITATION_TEXT_LIMIT,
                }
            ],
        )

    def test_import_source_from_pdf_pages_caps_pages_and_page_lengths(self):
        notebook = self.notebooks.create_notebook("Import PDF")

        source = self.notebooks.import_source(
            notebook["id"],
            {"url": "https://example.com/paper.pdf", "title": "", "kind": "paper"},
            {
                "url": "https://example.com/paper.pdf",
                "content_type": "application/pdf",
                "engine": "obscura-pdf",
                "text": "full document text",
                "pages": [
                    {"page": number, "text": f"page-{number}-" + ("x" * 2500)}
                    for number in range(1, 61)
                ],
            },
        )

        self.assertEqual(source["origin"], "import")
        self.assertEqual(source["content_type"], "application/pdf")
        self.assertEqual(source["engine"], "obscura-pdf")
        self.assertEqual(len(source["citations"]), self.notebooks._IMPORT_PAGE_LIMIT)
        self.assertEqual(source["citations"][0]["label"], "p. 1")
        self.assertEqual(source["citations"][0]["page"], 1)
        self.assertLessEqual(
            len(source["citations"][0]["text"]),
            self.notebooks._IMPORT_CITATION_TEXT_LIMIT,
        )
        self.assertEqual(
            source["citations"][-1]["page"],
            self.notebooks._IMPORT_PAGE_LIMIT,
        )
        self.assertLessEqual(len(source["excerpt"]), self.notebooks._EXCERPT_LIMIT)

    def test_import_source_falls_back_to_document_citation_without_pages(self):
        notebook = self.notebooks.create_notebook("Import fallback")

        source = self.notebooks.import_source(
            notebook["id"],
            {"url": "https://example.com/fallback.pdf", "title": "Fallback", "kind": "paper"},
            {
                "url": "https://example.com/fallback.pdf",
                "content_type": "application/pdf",
                "engine": "obscura-pdf",
                "text": "Readable PDF text without page extraction.",
                "pages": [],
            },
        )

        self.assertEqual(
            source["citations"],
            [
                {
                    "id": "source-1-doc",
                    "label": "document",
                    "text": "Readable PDF text without page extraction.",
                }
            ],
        )

    def test_tutor_context_uses_bounded_citation_labels(self):
        notebook = self.notebooks.create_notebook(
            "Tutor context",
            goal="Understand the paper",
        )
        self.notebooks.import_source(
            notebook["id"],
            {"url": "https://example.com/paper.pdf", "title": "Citation rich", "kind": "paper"},
            {
                "url": "https://example.com/paper.pdf",
                "content_type": "application/pdf",
                "engine": "obscura-pdf",
                "text": "full document text " * 800,
                "pages": [
                    {"page": 1, "text": "Intro " * 800},
                    {"page": 2, "text": "Methods " * 800},
                ],
            },
        )

        context = self.notebooks.build_tutor_context("tutor-context")

        self.assertIn("Notebook: Tutor context", context)
        self.assertIn("Source 1: Citation rich", context)
        self.assertIn("p. 1:", context)
        self.assertIn("p. 2:", context)
        self.assertLessEqual(len(context), self.notebooks._TUTOR_CONTEXT_LIMIT)
        self.assertNotIn("full document text full document text full document text", context)

    def test_tutor_citations_return_bounded_source_metadata(self):
        notebook = self.notebooks.create_notebook("Tutor citations")
        self.notebooks.import_source(
            notebook["id"],
            {"url": "https://example.com/paper.pdf", "title": "Paper", "kind": "paper"},
            {
                "url": "https://example.com/paper.pdf",
                "content_type": "application/pdf",
                "engine": "obscura-pdf",
                "text": "Readable paper text " * 100,
                "pages": [{"page": 1, "text": "Evidence " * 100}],
            },
        )

        citations = self.notebooks.tutor_citations(notebook["id"])

        self.assertEqual(citations[0]["source_id"], "source-1")
        self.assertEqual(citations[0]["label"], "p. 1")
        self.assertEqual(citations[0]["title"], "Paper")
        self.assertNotIn("text", citations[0])

    def test_delete_all_notebooks_returns_count_and_removes_files(self):
        first = self.notebooks.create_notebook("First notebook")
        second = self.notebooks.create_notebook("Second notebook")

        deleted = self.notebooks.delete_all_notebooks()

        self.assertEqual(deleted, 2)
        self.assertEqual(self.notebooks.list_notebooks(), [])
        self.assertFalse(os.path.exists(os.path.join(
            self.data_root, "workspace", "notebooks", f"{first['id']}.json"
        )))
        self.assertFalse(os.path.exists(os.path.join(
            self.data_root, "workspace", "notebooks", f"{second['id']}.json"
        )))

    def test_normalize_study_set_bounds_items_and_filters_unknown_citations(self):
        notebook = self.notebooks.create_notebook("Study normalization")
        self.notebooks.add_source(
            notebook["id"],
            {"title": "Source", "excerpt": "Bounded evidence."},
        )
        raw = {
            "mode": "flashcards",
            "items": [
                {
                    "front": "Known",
                    "back": "Answer " + ("x" * 2000),
                    "citation_ids": ["source-1-doc", "invented"],
                }
                for _ in range(20)
            ],
        }

        normalized = self.notebooks.normalize_study_set(
            raw, "flashcards", 5, notebook["id"]
        )

        self.assertEqual(len(normalized["items"]), 5)
        self.assertLessEqual(len(normalized["items"][0]["back"]), 1200)
        self.assertEqual(normalized["items"][0]["citation_ids"], ["source-1-doc"])

    def test_save_study_set_persists_stable_card_ids_and_due_count(self):
        notebook = self.notebooks.create_notebook("Saved study")
        saved = self.notebooks.save_study_set(
            notebook["id"],
            {
                "mode": "flashcards",
                "items": [{"front": "Front", "back": "Back", "citation_ids": []}],
            },
        )

        self.assertEqual(saved["id"], "study-set-1")
        self.assertEqual(saved["items"][0]["id"], "card-1")
        self.assertEqual(saved["items"][0]["status"], "learning")
        self.assertEqual(self.notebooks.review_due_count(notebook["id"]), 1)
        self.assertEqual(
            self.notebooks.read_notebook(notebook["id"])["study_sets"][0]["id"],
            "study-set-1",
        )

    def test_review_rating_updates_card_schedule_and_due_count(self):
        notebook = self.notebooks.create_notebook("Review scheduling")
        saved = self.notebooks.save_study_set(
            notebook["id"],
            {
                "mode": "flashcards",
                "items": [{"front": "Front", "back": "Back", "citation_ids": []}],
            },
        )

        reviewed = self.notebooks.review_study_item(
            notebook["id"],
            {
                "study_set_id": saved["id"],
                "item_id": saved["items"][0]["id"],
                "rating": "got_it",
            },
        )

        item = reviewed["study_set"]["items"][0]
        self.assertEqual(item["repetitions"], 1)
        self.assertEqual(item["status"], "review")
        self.assertGreater(item["interval_days"], 0)
        self.assertEqual(reviewed["review_due_count"], 0)
        with self.assertRaisesRegex(ValueError, "rating"):
            self.notebooks.review_study_item(
                notebook["id"],
                {
                    "study_set_id": saved["id"],
                    "item_id": saved["items"][0]["id"],
                    "rating": "perfect",
                },
            )

    def test_store_uses_workspace_notebooks_files(self):
        notebook = self.notebooks.create_notebook("My notebook")
        target = os.path.join(self.data_root, "workspace", "notebooks", f"{notebook['id']}.json")
        self.assertTrue(os.path.isfile(target))
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["id"], notebook["id"])
        self.assertIn("learning_path", data)


if __name__ == "__main__":
    unittest.main()
