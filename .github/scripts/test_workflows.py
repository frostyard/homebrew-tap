"""Unit tests for the shell and pipefail settings in GitHub workflows."""

import re
import unittest
from pathlib import Path


def check_defaults(text):
    """Require a top-level defaults block with bash run shell."""
    lines = text.splitlines()
    found = False

    for index, line in enumerate(lines):
        if line == "defaults:":
            found = True
            block = []
            for candidate in lines[index + 1:]:
                if not candidate.strip():
                    continue
                if candidate.startswith("#"):
                    continue
                if candidate[0].isspace():
                    block.append(candidate)
                    continue
                break

            if "  run:" not in block or "    shell: bash" not in block:
                return False

    return found


def check_shell_lines(text):
    """Reject shell overrides; the only accepted spelling is ``shell: bash``.

    Shell settings may appear at step level or in inline YAML. Any other
    spelling, including quoted keys and shell arguments, is reported by line.
    """
    shell_pattern = re.compile(r'''(^|[\s{,-])["']?shell["']?\s*:''')
    allowed = re.compile(r"\s*(-\s+)?shell:\s*bash\s*")
    bad_lines = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if shell_pattern.search(line) and allowed.fullmatch(line) is None:
            bad_lines.append((line_number, line))

    return bad_lines


class WorkflowShellTests(unittest.TestCase):
    def test_repository_workflows(self):
        workflow_dir = Path(__file__).resolve().parent.parent / "workflows"

        workflows = sorted(
            set(workflow_dir.glob("*.yml")) | set(workflow_dir.glob("*.yaml"))
        )
        # An empty list would pass every check: require the known workflows.
        names = {workflow.name for workflow in workflows}
        for required in (
            "brew-tarball.yml",
            "bump.yml",
            "ci.yml",
            "publish.yml",
            "risk-paths.yml",
            "tests.yml",
        ):
            self.assertIn(required, names)

        for workflow in workflows:
            text = workflow.read_text(encoding="utf-8")
            with self.subTest(workflow=workflow.name):
                self.assertTrue(check_defaults(text), "missing top-level defaults.run.shell: bash")
                bad_shell_lines = check_shell_lines(text)
                self.assertEqual(
                    bad_shell_lines,
                    [],
                    "shell settings must use only 'shell: bash'; bad lines: "
                    + "; ".join(f"{number}: {line}" for number, line in bad_shell_lines),
                )

    def test_old_brew_tarball_fixture_fails_defaults_check(self):
        old_text = '''name: Generate Homebrew Tarball and Release

permissions: {}

jobs:
  push_tarballs:
    steps:
      - run: |
          "sha${spice}sum" "$OUTDIR/$TARBALL_FILENAME" | tee "$SHASUM_DIR/homebrew-$(arch).sha${spice}"
'''
        self.assertFalse(check_defaults(old_text))

    def test_step_shell_sh_fixture_fails_shell_check(self):
        text = '''jobs:
  build:
    steps:
      - run: echo test
        shell: sh
'''
        self.assertNotEqual(check_shell_lines(text), [])

    def test_shell_override_fixtures_fail_closed(self):
        fixtures = {
            "shell first key": """jobs:
  build:
    steps:
      - shell: sh
        run: echo test
""",
            "single quoted shell key": """jobs:
  build:
    steps:
      - run: echo test
        'shell': sh
""",
            "double quoted shell key": """jobs:
  build:
    steps:
      - run: echo test
        "shell": sh
""",
            "inline job default": """jobs:
  build:
    defaults: {run: {shell: sh}}
""",
            "shell arguments": """jobs:
  build:
    steps:
      - run: echo test
        shell: bash -e {0}
""",
        }

        for name, text in fixtures.items():
            with self.subTest(fixture=name):
                bad_lines = check_shell_lines(text)
                self.assertNotEqual(
                    bad_lines,
                    [],
                    "fixture must fail: bad shell line was not detected",
                )

    def test_bash_shell_fixture_passes(self):
        text = """jobs:
  build:
    steps:
      - shell: bash
        run: echo test
      - run: echo also-test
        shell: bash
"""
        self.assertEqual(check_shell_lines(text), [])

    def test_defaults_fixture_passes(self):
        text = '''permissions: {}

# Explicit bash runs every step with -eo pipefail.
defaults:
  run:
    shell: bash

jobs:
  build:
'''
        self.assertTrue(check_defaults(text))
        self.assertEqual(check_shell_lines(text), [])


if __name__ == "__main__":
    unittest.main()
