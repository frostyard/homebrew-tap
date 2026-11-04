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
    """Require every workflow shell setting to use bash exactly."""
    shell_pattern = re.compile(r"^\s*shell:")

    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if shell_pattern.match(line):
            if stripped != "shell: bash":
                return False

    return True


class WorkflowShellTests(unittest.TestCase):
    def test_repository_workflows(self):
        workflow_dir = Path(__file__).resolve().parent.parent / "workflows"

        for workflow in sorted(workflow_dir.glob("*.yml")):
            text = workflow.read_text(encoding="utf-8")
            with self.subTest(workflow=workflow.name):
                self.assertTrue(check_defaults(text), "missing top-level defaults.run.shell: bash")
                self.assertTrue(check_shell_lines(text), "shell setting is not exactly bash")

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
        self.assertFalse(check_shell_lines(text))

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
        self.assertTrue(check_shell_lines(text))


if __name__ == "__main__":
    unittest.main()
