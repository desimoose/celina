import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import sys

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import projects  # noqa: E402


class ProjectsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.temp.name, "projects")
        self.patch = mock.patch.object(
            projects.paths, "projects_dir", return_value=self.root
        )
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_create_list_save_and_read_output(self):
        project = projects.create_project("Sleep research")
        self.assertEqual(project["id"], "sleep-research")
        saved = projects.save_output(
            project["id"], "caffeine", "markdown", "# Caffeine\n"
        )
        self.assertEqual(saved["format"], "markdown")
        self.assertEqual(projects.read_output(project["id"], saved["name"]), "# Caffeine\n")
        listed = projects.list_projects()
        self.assertEqual(listed[0]["name"], "Sleep research")
        self.assertEqual(listed[0]["outputs"][0]["name"], saved["name"])

    def test_project_names_are_local_folders_and_ids_are_unique(self):
        first = projects.create_project("Field notes")
        second = projects.create_project("Field notes")
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(os.path.isdir(os.path.join(self.root, first["id"], "outputs")))
        with self.assertRaises(ValueError):
            projects.save_output(first["id"], "bad", "pdf", "no")

    def test_project_dir_rejects_symlink_escape_with_existing_error(self):
        root = Path(self.root)
        root.mkdir(parents=True, exist_ok=True)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = root / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        with self.assertRaisesRegex(ValueError, "project path escapes projects root"):
            projects._project_dir("linked")

    def test_concurrent_output_writes_get_distinct_atomic_files(self):
        project = projects.create_project("Concurrent outputs")
        barrier = threading.Barrier(8)
        errors = []

        def write_output(index):
            try:
                barrier.wait(timeout=5)
                projects.save_output(
                    project["id"],
                    "same title",
                    "markdown",
                    f"# Output {index}\n",
                )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=write_output, args=(index,))
            for index in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        listed = projects.list_projects()
        self.assertEqual(len(listed[0]["outputs"]), 8)


if __name__ == "__main__":
    unittest.main()
