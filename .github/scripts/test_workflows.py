"""Unit tests for the shell and pipefail settings in GitHub workflows."""

import re
import unittest
from pathlib import Path

import bump_casks


def check_workflow_dispatch(text):
    """Require ``workflow_dispatch:`` inside the top-level ``on:`` block."""
    lines = text.splitlines()
    if "on:" not in lines:
        return False

    for line in lines[lines.index("on:") + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            return False
        if line.rstrip() == "  workflow_dispatch:":
            return True

    return False


def job_lines(text, job):
    """Return the lines of one job's block, or [] when the job is absent."""
    lines = text.splitlines()
    header = f"  {job}:"
    if header not in lines:
        return []

    block = []
    for line in lines[lines.index(header) + 1:]:
        if line.strip() and not line.startswith("    "):
            break
        block.append(line)
    return block


def check_job_permission(text, job, scope):
    """Require ``<scope>: write`` in the job's own ``permissions:`` block."""
    lines = job_lines(text, job)

    for index, line in enumerate(lines):
        if line.rstrip() != "    permissions:":
            continue
        for candidate in lines[index + 1:]:
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                continue
            if candidate.split("#", 1)[0].rstrip() == f"      {scope}: write":
                return True
            if not candidate.startswith("      "):
                break

    return False


PULL_REQUEST_TARGET = re.compile(r"(?<![\w-])pull_request_target(?![\w-])")

# The only workflow that may run on pull_request_target: the PR triage caller.
# GitHub blocks that event by default in a public repository from 2026-12-02,
# and the organization's Actions policy allows it for the caller path only
# (frostyard/core docs/design/pull-request-target-policy.md).
PULL_REQUEST_TARGET_ALLOWED = {"risk-paths.yml"}


def mentions_pull_request_target(text):
    """True when the text names ``pull_request_target`` anywhere.

    It fails closed: it parses no YAML and strips no comment, so every form
    of the trigger counts (a scalar, a flow or block list, a mapping key, a
    quoted key, an anchor), and so does the word in a comment, a quoted value
    or a script. Only a longer name that holds the word is not a match. A
    workflow that must name the event in a comment cannot: write "the
    target event" instead.
    """
    return PULL_REQUEST_TARGET.search(text) is not None


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


class BumpPullRequestChecksTests(unittest.TestCase):
    """A pull request from bump.yml gets its checks from a dispatch (issue #42)."""

    def workflow_dir(self):
        """Return the directory of the repository's workflows."""
        return Path(__file__).resolve().parent.parent / "workflows"

    def test_check_workflows_run_on_workflow_dispatch(self):
        for name in bump_casks.CHECK_WORKFLOWS:
            text = (self.workflow_dir() / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertTrue(
                    check_workflow_dispatch(text),
                    f"{name}: missing a top-level on.workflow_dispatch key",
                )

    def test_bump_job_may_start_workflows(self):
        text = (self.workflow_dir() / "bump.yml").read_text(encoding="utf-8")
        self.assertTrue(
            check_job_permission(text, "bump", "actions"),
            "bump.yml: the bump job needs actions: write for gh workflow run",
        )

    def test_workflow_dispatch_fixture_passes(self):
        text = """on:
  pull_request:
    branches: [main]
  workflow_dispatch:
"""
        self.assertTrue(check_workflow_dispatch(text))

    def test_workflow_fixture_without_dispatch_fails(self):
        text = """on:
  pull_request:
"""
        self.assertFalse(check_workflow_dispatch(text))

    def test_nested_workflow_dispatch_fixture_fails(self):
        text = """on:
  push:
    workflow_dispatch:
"""
        self.assertFalse(check_workflow_dispatch(text))

    def test_job_permission_fixtures(self):
        with_actions = """jobs:
  bump:
    runs-on: ubuntu-24.04
    permissions:
      contents: write
      actions: write # gh workflow run
"""
        self.assertTrue(check_job_permission(with_actions, "bump", "actions"))
        self.assertFalse(check_job_permission(with_actions, "bump", "pull-requests"))
        self.assertFalse(check_job_permission(with_actions, "other", "actions"))


class PullRequestTargetTests(unittest.TestCase):
    def test_only_the_triage_caller_uses_pull_request_target(self):
        workflow_dir = Path(__file__).resolve().parent.parent / "workflows"
        workflows = sorted(
            set(workflow_dir.glob("*.yml")) | set(workflow_dir.glob("*.yaml"))
        )
        users = {
            workflow.name
            for workflow in workflows
            if mentions_pull_request_target(workflow.read_text(encoding="utf-8"))
        }
        # The caller must keep the event: without it, this check passes on
        # an empty set and proves nothing.
        self.assertEqual(users, PULL_REQUEST_TARGET_ALLOWED)

    def test_pull_request_target_fixtures(self):
        found = {
            "scalar": "on: pull_request_target\n",
            "flow list": "on: [push, pull_request_target]\n",
            "block list": "on:\n  - push\n  - pull_request_target\n",
            "mapping": "on:\n  pull_request_target:\n    types: [labeled]\n",
            "quoted key": "'on':\n  \"pull_request_target\": {}\n",
            "comment after": "on:\n  pull_request_target: # base\n",
            "bom": "\ufeffon: pull_request_target\n",
            "no final newline": "on: pull_request_target",
            "crlf": "on:\r\n  pull_request_target:\r\n",
            "hash in a quoted value": 'on: {push: {branches: ["release#1"]}, pull_request_target: {}}\n',
            "flow mapping": "on: {pull_request_target: {types: [labeled]}}\n",
            "anchor": "name: &event pull_request_target\non: [*event]\n",
            "block scalar": "jobs:\n  a:\n    steps:\n      - run: |\n          echo pull_request_target\n",
            "comment only": "# pull_request_target is not used\non:\n  pull_request:\n",
        }
        for name, text in found.items():
            with self.subTest(name=name):
                self.assertTrue(mentions_pull_request_target(text))

        not_found = {
            "empty": "",
            "other event": "on:\n  pull_request:\n    types: [labeled]\n",
            "longer name": "on:\n  pull_request_target_x:\n",
            "hyphen prefix": "env:\n  NAME: no-pull_request_target\n",
        }
        for name, text in not_found.items():
            with self.subTest(name=name):
                self.assertFalse(mentions_pull_request_target(text))


if __name__ == "__main__":
    unittest.main()
