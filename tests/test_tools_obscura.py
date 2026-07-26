import os
import sys
import unittest

SERVER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server"))
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import paths  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
