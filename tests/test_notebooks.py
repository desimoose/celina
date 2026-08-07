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
