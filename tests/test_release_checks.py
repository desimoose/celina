import importlib.util
from pathlib import Path
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_release.py"

CI_COMMANDS = (
    "python -m unittest discover -s tests -q",
    "node --test tests/test_privacy_ui.js tests/test_search_capture.js",
    "python -c \"import pathlib, py_compile; [py_compile.compile(str(p), doraise=True) for p in pathlib.Path('server').glob('*.py')]\"",
    "node --check web/app.js",
    "git diff --check",
    "python scripts/verify_release.py",
)

PROVIDER_URL = "https://api.openai.com/v1/chat/completions"


def _load_verifier():
    if not VERIFIER_PATH.is_file():
        return None
    spec = importlib.util.spec_from_file_location("verify_release", VERIFIER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseChecksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, relative, content=""):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def _write_valid_repository(self):
        security = f"""
            # Security policy

            Provider requests are user-initiated and may use this explicit gateway:
            `{PROVIDER_URL}`
        """
        self._write("SECURITY.md", security)
        self._write("docs/SECURITY_MODEL.md", "# Security model\nNO_TELEMETRY\n")
        self._write("docs/OPERATIONS.md", "# Operations\nRun release checks before shipping.\n")
        self._write("CONTRIBUTING.md", "\n".join(CI_COMMANDS))
        workflow = "name: CI\non: [push, pull_request]\nsteps:\n" + "\n".join(
            f"  - run: {command}" for command in CI_COMMANDS
        )
        self._write(".github/workflows/ci.yml", workflow)
        self._write(".env.example", "OPENAI_API_KEY=\n")
        self._write(
            "server/gateway.py",
            f'PROVIDERS = {{"openai": {{"url": "{PROVIDER_URL}"}}}}\n',
        )
        self._write("web/app.js", "const ready = true;\n")

    def _verifier(self):
        verifier = _load_verifier()
        self.assertIsNotNone(verifier, "scripts/verify_release.py must exist")
        return verifier

    def test_required_documents_and_ci_commands_are_enforced(self):
        verifier = self._verifier()
        self._write_valid_repository()
        (self.root / "docs" / "OPERATIONS.md").unlink()
        workflow = self.root / ".github" / "workflows" / "ci.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8").replace(
                f"  - run: {CI_COMMANDS[-1]}", ""
            ),
            encoding="utf-8",
        )

        issues = verifier.check_repository(self.root)

        self.assertTrue(any("docs/OPERATIONS.md" in issue for issue in issues))
        self.assertTrue(any("required command" in issue for issue in issues))

    def test_clean_repository_and_empty_env_template_are_accepted(self):
        verifier = self._verifier()
        self._write_valid_repository()

        self.assertEqual(verifier.check_repository(self.root), [])

    def test_committed_secret_assignment_is_rejected_without_echoing_value(self):
        verifier = self._verifier()
        self._write_valid_repository()
        secret = "sk-" + "test-secret"
        self._write("server/leak.py", f'OPENAI_API_KEY = "{secret}"\n')

        issues = verifier.check_repository(self.root)

        self.assertTrue(any("possible secret" in issue for issue in issues))
        self.assertFalse(any(secret in issue for issue in issues))

    def test_analytics_and_crash_reporting_dependencies_are_rejected(self):
        verifier = self._verifier()
        self._write_valid_repository()
        dependency = "post" + "hog"
        self._write("requirements.txt", f"{dependency}==3.0\n")
        self._write("server/metrics.py", "import " + dependency + "\n")

        issues = verifier.check_repository(self.root)

        self.assertTrue(any("telemetry dependency" in issue for issue in issues))

    def test_tracking_urls_and_product_event_uploads_are_rejected(self):
        verifier = self._verifier()
        self._write_valid_repository()
        tracking_url = "https://events." + "example/track"
        self._write(
            "web/metrics.js",
            f'fetch("{tracking_url}", {{method: "POST", body: event}});\n',
        )

        issues = verifier.check_repository(self.root)

        self.assertTrue(any("tracking or telemetry URL" in issue for issue in issues))

    def test_remote_feature_flag_clients_are_rejected(self):
        verifier = self._verifier()
        self._write_valid_repository()
        client = "launch" + "darkly"
        self._write("server/flags.py", "import " + client + "\n")

        issues = verifier.check_repository(self.root)

        self.assertTrue(any("remote feature flag" in issue for issue in issues))

    def test_documented_provider_gateway_url_is_allowed(self):
        verifier = self._verifier()
        self._write_valid_repository()

        issues = verifier.check_repository(self.root)

        self.assertFalse(any("provider gateway" in issue for issue in issues))

    def test_undocumented_provider_gateway_url_is_rejected(self):
        verifier = self._verifier()
        self._write_valid_repository()
        self._write("SECURITY.md", "# Security policy\n")

        issues = verifier.check_repository(self.root)

        self.assertTrue(any("provider gateway" in issue for issue in issues))

    def test_real_ci_workflow_contains_plan_commands_exactly(self):
        workflow = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(workflow.is_file(), ".github/workflows/ci.yml must exist")
        text = workflow.read_text(encoding="utf-8")
        for command in CI_COMMANDS:
            self.assertIn(f"- run: {command}", text)


if __name__ == "__main__":
    unittest.main()
