import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import storage  # noqa: E402


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_safe_child_accepts_nested_relative_path(self):
        expected = os.path.realpath(self.root / "notes" / "state.json")

        self.assertEqual(
            storage.safe_child(self.root, os.path.join("notes", "state.json")),
            expected,
        )

    def test_safe_child_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            storage.safe_child(self.root, os.path.join("..", "outside.json"))

    def test_safe_child_rejects_absolute_path(self):
        absolute = Path(self.temp.name) / "outside.json"

        with self.assertRaises(ValueError):
            storage.safe_child(self.root, absolute)

    def test_safe_child_rejects_symlink_escape(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")

        with self.assertRaises(ValueError):
            storage.safe_child(self.root, os.path.join("link", "secret.txt"))

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_safe_child_rejects_junction_escape(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        junction = self.root / "junction"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"junction creation is unavailable: {result.stderr.strip()}")

        with self.assertRaises(ValueError):
            storage.safe_child(self.root, os.path.join("junction", "secret.txt"))

    def test_interrupted_atomic_write_leaves_previous_json_readable(self):
        target = self.root / "state.json"
        previous = {"records": ["previous"]}
        storage.atomic_write_json(target, previous)

        def interrupt_replace(_source, _destination):
            raise OSError("simulated interruption")

        with self.assertRaisesRegex(OSError, "simulated interruption"):
            storage.atomic_write_bytes(
                target,
                json.dumps({"records": ["replacement"]}).encode("utf-8"),
                replace_func=interrupt_replace,
            )

        with target.open("r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), previous)
        self.assertEqual([item.name for item in self.root.iterdir()], ["state.json"])

    def test_concurrent_locked_writes_preserve_every_record(self):
        target = self.root / "records.json"
        storage.atomic_write_json(target, {"records": []})
        barrier = threading.Barrier(8)
        errors = []

        def add_record(index):
            try:
                barrier.wait(timeout=5)
                with storage.locked(target):
                    with target.open("r", encoding="utf-8") as handle:
                        state = json.load(handle)
                    state["records"].append(index)
                    storage.atomic_write_json(target, state)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=add_record, args=(index,))
            for index in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        with target.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(sorted(state["records"]), list(range(8)))


if __name__ == "__main__":
    unittest.main()
