import importlib
import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)


class PathsTest(unittest.TestCase):
    def setUp(self):
        # Reload paths fresh each test so module-level state can't leak,
        # and clear the env override.
        os.environ.pop("REVERIEBOT_HOME", None)
        import paths
        self.paths = importlib.reload(paths)

    def tearDown(self):
        os.environ.pop("REVERIEBOT_HOME", None)

    def test_dev_data_dir_is_repo_root(self):
        # Not frozen (running under a normal interpreter) -> repo root.
        repo_root = os.path.abspath(os.path.join(SERVER, ".."))
        self.assertEqual(
            os.path.realpath(self.paths.data_dir()),
            os.path.realpath(repo_root),
        )

    def test_override_wins(self):
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "reveriebot_test_home")
        os.environ["REVERIEBOT_HOME"] = tmp
        self.assertEqual(
            os.path.realpath(self.paths.data_dir()),
            os.path.realpath(tmp),
        )
        self.assertTrue(os.path.isdir(tmp))

    def test_web_dir_ends_with_web(self):
        self.assertTrue(self.paths.web_dir().replace("\\", "/").endswith("/web"))

    def test_workspace_dir_is_created_under_data_dir(self):
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "reveriebot_test_home2")
        os.environ["REVERIEBOT_HOME"] = tmp
        ws = self.paths.workspace_dir()
        self.assertTrue(os.path.isdir(ws))
        self.assertEqual(
            os.path.realpath(os.path.dirname(ws)), os.path.realpath(tmp)
        )

    def test_env_file_under_data_dir(self):
        tmp = os.path.join(os.environ.get("TEMP", "/tmp"), "reveriebot_test_home3")
        os.environ["REVERIEBOT_HOME"] = tmp
        self.assertEqual(
            os.path.realpath(self.paths.env_file()),
            os.path.realpath(os.path.join(tmp, ".env")),
        )


if __name__ == "__main__":
    unittest.main()
