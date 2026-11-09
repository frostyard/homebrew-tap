"""The repository baseline: core ADR-0071, rows B1 to B17 that apply here.

Each check is a function that takes a repository root. It raises BaselineError
with the row ID and what is wrong, or returns None. The tests at the bottom run
each check on this tree, then break each row in a copy outside the repository
and assert that the check fails (a guard needs a negative test of its own).

Row B3 (the docs shape) is exempt for this repository: the tap is Homebrew
casks and formulae only (core's repository-baseline spec, Exemptions).

The checks port the canonical rules where they exist, rather than matching a
substring:

- B2: core's `.memory` gate, `scripts/check-corrections.mjs`: the 5 fields, a
  calendar-valid date, a non-blank scope, correction and evidence, an empty
  `promoted_to` allowed, and no blank line, no duplicate key and no BOM.
  The append-only rule against a base ref is not ported here: it needs git.
- B5: `persist-credentials: false` on every checkout and top-level read-only
  permissions. Every `uses:` is a 40-character commit SHA with a version
  comment after it. The top-level `defaults.run.shell: bash` block that the
  tap needs is checked by .github/scripts/test_workflows.py.
- B6: the risk-paths spec's document rules of schema version 2, ported from
  core's `scripts/lib/risk-paths.mjs` (`validateRiskPaths`, `validateGlob`,
  `checkRequiredPaths`): the exact top-level keys, `schema_version: 2`, a
  `default_level` in L1 to L4, a `level` in L1 to L4 on every entry, the glob
  syntax, no duplicate glob, and a `why` that is at most 200 characters and
  names a category. Rule C with levels: every glob that matches the list or the
  caller is L1 or L2. The required paths of this repository must match a glob:
  the list itself, the caller, the bump, tarball and publish workflows, the
  bump script and the 2 casks. The caller calls core's `pr-triage.yml` at a
  40-character commit SHA, on `pull_request_target`, with the type `labeled`,
  in a job named `pr-triage`, and with top-level `permissions: {}`.
- B10: `LICENSE` is MIT or GPL-3.0. The repository's license metadata on
  GitHub (`gh api repos/<owner>/<repo> --jq .license.spdx_id`) is outside this
  check: the tree cannot show it.
- B12: `ci.yml` runs on the `pull_request` event and has a `run: make ci` step
  that no `if:` disables.
- B17: the README spec's rules R1 to R12, ported from core's
  `.agents/skills/frostyard-readme/scripts/check-readme.mjs`. R12's emoji rule
  is not ported: Python's `re` has no `Extended_Pictographic` property. Core's
  checker covers it: run
  `node <core-checkout>/.agents/skills/frostyard-readme/scripts/check-readme.mjs <clone>`
  from a core checkout.
"""

import datetime
import json
import os
import re
import shutil
import tempfile
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

ALIASES = ("CLAUDE.md", "GEMINI.md", ".cursorrules", ".github/copilot-instructions.md")
CORRECTION_KEYS = ("date", "scope", "correction", "evidence", "promoted_to")
CORRECTIONS_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FRAMEWORK_TREES = ("docs/superpowers", ".planning", ".cursor/rules", ".gaai", "yeti", "cairn")
MAX_WHY_LENGTH = 200
MAX_BRACE_EXPANSIONS = 256
LEVELS = ("L1", "L2", "L3", "L4")
STRICT_LEVELS = ("L1", "L2")
SCHEMA_VERSION = 2
LIST_KEYS = ("schema_version", "default_level", "paths")
ENTRY_KEYS = ("glob", "level", "why")
WHY_CATEGORY = re.compile(
    r"^(?:boot chain|signing and keys|update verification|auth|publication|"
    r"secrets and credentials|rulesets and settings|destructive operations|governance): \S")
RISK_LIST = ".github/risk-paths.json"
CORE_PR_TRIAGE = re.compile(
    r"uses:\s+frostyard/core/\.github/workflows/pr-triage\.yml@[0-9a-f]{40}(?:\s|$)")
CALLER_JOB = "pr-triage"
PINNED_USES = re.compile(r"frostyard/core/\.github/workflows/pr-triage\.yml@[0-9a-f]{40}")
JOB_USES = re.compile(r"^ {4}uses:[ \t]*(.*)$")
BLOCK_SCALAR = re.compile(r"^(\s*)(?:-\s+)?[\w.-]+:[ \t]+[|>][-+0-9]*[ \t]*(?:#.*)?$")
REQUIRED_RISK_PATHS = (
    RISK_LIST,
    ".github/workflows/bump.yml",
    ".github/workflows/brew-tarball.yml",
    ".github/workflows/publish.yml",
    ".github/scripts/bump_casks.py",
    "Casks/chairlift.rb",
    "Casks/nsl.rb",
)
CALLER = ".github/workflows/risk-paths.yml"
PERMISSION_ITEM = re.compile(r"^(\s+)([\w-]+):\s*(\S+)\s*$")
LIST_ITEM = re.compile(r"^(\s*)-(?:\s(.*))?$")
USES = re.compile(r"^\s*(?:-\s+)?uses:\s+(\S+)")
JOB = re.compile(r"^ {2}([\w-]+):\s*$")
RUN_MAKE_CI = re.compile(r"^\s*(?:-\s+)?run:\s*make ci\s*$")
STEP_IF = re.compile(r"^\s*(?:-\s+)?if:")
JOB_IF = re.compile(r"^ {4}if:")

README_KINDS = {
    "org": {"required": ["What is here", "Use"], "optional": []},
    "image": {"required": ["Images", "Install"], "optional": []},
    "packaging": {"required": ["What it publishes", "Install"], "optional": ["Add a package"]},
    "app": {"required": ["What it does", "Install"], "optional": ["Remove"]},
    "extension": {"required": ["What it does", "Install"], "optional": ["Settings", "Remove"]},
    "tool": {"required": ["What it does", "Install", "Use"], "optional": []},
    "website": {"required": ["What the site covers", "Deploy"], "optional": []},
    "service": {"required": ["What it does", "Deploy"], "optional": ["Interface"]},
    "library": {"required": ["What it does", "Install", "Use"], "optional": []},
    "infrastructure": {"required": ["What is here", "Use"], "optional": []},
}
README_COMMON_OPTIONAL = ["Requirements", "How it works", "Problem records", "Privacy", "Limits", "Credits"]
README_LAST = ["Develop", "Where to go next"]
README_STATUS = ["pre-release", "stable", "in production", "maintenance", "deprecated"]
README_MARKER = re.compile(r"^<!--\s*readme-kind:\s*([a-z-]+)\s*-->$")
README_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
README_FENCE = re.compile(r"^(`{3,}|~{3,})")
README_STATUS_PREFIX = "**Status:**"
README_DOC_PREFIX = "**Documentation:**"
README_TAGLINE = re.compile(r"^\*\*[^*]+\*\*$")
README_INLINE_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?\s*\)")
README_AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
README_BADGE = re.compile(r"\[!\[[^\]]*\]\(([^)\s]+)\)\]\(([^)\s]+)\)")
README_PRIVATE_V4 = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3})(?!\.?\d)")
README_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
README_BADGE_HOSTS = ("api.scorecard.dev", "codecov.io")


class BaselineError(AssertionError):
    """A baseline row fails."""


def fail(row, message):
    raise BaselineError(f"{row}: {message}")


def read(root, name):
    """The text of a file under root; a missing file gives None."""
    path = Path(root) / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def workflows(root):
    """The path and text of each workflow: GitHub runs both `.yml` and `.yaml`."""
    folder = Path(root) / ".github" / "workflows"
    if not folder.is_dir():
        return []
    paths = sorted(set(folder.glob("*.yml")) | set(folder.glob("*.yaml")))
    return [(path, path.read_text(encoding="utf-8")) for path in paths]


def indented_block(lines, start):
    """The lines of the list item that starts at start, without its siblings."""
    indent = len(LIST_ITEM.match(lines[start]).group(1))
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip():
            block.append(line)
            continue
        current = len(line) - len(line.lstrip())
        if current < indent:
            break
        item = LIST_ITEM.match(line)
        if item and len(item.group(1)) == indent:
            break
        block.append(line)
    return block


def top_permissions(text):
    """The top-level `permissions:` key: (inline value, granted scopes) or (None, [])."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not line.startswith("permissions:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value:
            return value, []
        granted = []
        for following in lines[index + 1:]:
            if not following.strip():
                continue
            item = PERMISSION_ITEM.match(following)
            if not item:
                break
            granted.append((item.group(2), item.group(3)))
        return "", granted
    return None, []


def workflow_events(text):
    """The event names of a workflow's `on:` key, in the yaml forms this file uses."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not re.match(r"^on:", line):
            continue
        value = line.split(":", 1)[1].strip()
        if value.startswith("["):
            return [name.strip().strip("'\"") for name in value.strip("[]").split(",") if name.strip()]
        if value:
            return [value.strip("'\"")]
        events = []
        indent = None
        for following in lines[index + 1:]:
            if not following.strip():
                continue
            item = re.match(r"^(\s+)([\w-]+):", following)
            if not item:
                if not following.startswith((" ", "\t")):
                    break
                continue
            if indent is None:
                indent = len(item.group(1))
            if len(item.group(1)) != indent:
                continue
            events.append(item.group(2))
        return events
    return []


def caller_types(text):
    """The `types:` names of the `on: pull_request_target:` trigger.

    [] when the trigger lists no types, and None when the workflow has no such
    trigger: a `types:` list of another trigger is not the caller's.
    """
    lines = text.split("\n")
    on_at = next((index for index, line in enumerate(lines) if re.fullmatch(r"on:[ \t]*", line)), None)
    if on_at is None:
        return None
    trigger_at = None
    for index in range(on_at + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if not line[:1].isspace():
            return None
        if re.fullmatch(r" {2}pull_request_target:[ \t]*", line):
            trigger_at = index
            break
    if trigger_at is None:
        return None
    for index in range(trigger_at + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= 2:
            return []
        found = re.fullmatch(r" {4}types:[ \t]*\[(.*)\][ \t]*", line)
        if found:
            return [name.strip() for name in found.group(1).split(",") if name.strip()]
    return []


def job_blocks(text):
    """The lines of each job of the top-level `jobs:` mapping, by job name.

    The mapping ends at the next top-level key, and a line of a block scalar is
    script text, not a job header: a `run-name: |` block that holds a job-like
    line creates no job.
    """
    lines = text.split("\n")
    start = next((index for index, line in enumerate(lines) if line == "jobs:"), None)
    if start is None:
        return {}
    blocks = {}
    current = None
    block_indent = -1
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        if not line[0].isspace():
            break
        indent = len(line) - len(line.lstrip())
        if block_indent >= 0:
            if indent > block_indent:
                continue
            block_indent = -1
        header = JOB.match(line)
        if header:
            current = header.group(1)
            blocks[current] = []
            continue
        started = BLOCK_SCALAR.match(line)
        if started:
            block_indent = len(started.group(1))
        if current is not None:
            blocks[current].append(line)
    return blocks


def job_uses(block_lines):
    """The value of a job's ``uses:`` key at indent 4, without its comment.

    None when the job has no such key. A blank or comment-only line at any
    indent is skipped, and a line under a ``run: |`` or ``run: >`` block scalar
    is script text, not a workflow key, so it does not count.
    """
    block_indent = -1
    for line in block_lines:
        stripped = line.strip()
        # A blank or comment-only line is not a key and not the end of the job:
        # it neither counts as the job's uses: nor ends a block scalar early.
        if stripped == "" or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if block_indent >= 0:
            if indent > block_indent:
                continue
            block_indent = -1
        found = JOB_USES.match(line)
        if found:
            return re.sub(r"[ \t]+#.*$", "", found.group(1)).strip()
        started = BLOCK_SCALAR.match(line)
        if started:
            block_indent = len(started.group(1))
    return None


def check_b1(root):
    """AGENTS.md is a regular file; the 4 aliases are relative symlinks to it."""
    path = Path(root) / "AGENTS.md"
    if path.is_symlink() or not path.is_file():
        fail("B1", "AGENTS.md is not a regular file")
    for name in ALIASES:
        alias = Path(root) / name
        if not alias.is_symlink():
            fail("B1", f"{name} is not a symlink to AGENTS.md")
        target = os.readlink(alias)
        if os.path.isabs(target):
            fail("B1", f"{name} has the absolute target {target}; use a relative one")
        if (alias.parent / target).resolve() != path.resolve():
            fail("B1", f"{name} resolves to {target}, not to AGENTS.md")


def check_b2(root):
    """.memory/corrections.jsonl, by core's scripts/check-corrections.mjs rules."""
    text = read(root, ".memory/corrections.jsonl")
    if text is None:
        fail("B2", ".memory/corrections.jsonl is missing")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for number, line in enumerate(lines, start=1):
        if line.strip() == "":
            fail("B2", f"line {number}: blank line")
        duplicates = []

        def collect(pairs):
            names = [name for name, _ in pairs]
            duplicates.extend(sorted({name for name in names if names.count(name) > 1}))
            return dict(pairs)

        try:
            entry = json.loads(line, object_pairs_hook=collect)
        except ValueError as error:
            fail("B2", f"line {number}: invalid JSON: {error}")
        if not isinstance(entry, dict):
            fail("B2", f"line {number}: not a plain object")
        if duplicates:
            fail("B2", f"line {number}: duplicate key(s): {', '.join(duplicates)}")
        missing = [key for key in CORRECTION_KEYS if key not in entry]
        unknown = [key for key in entry if key not in CORRECTION_KEYS]
        if missing or unknown:
            parts = []
            if missing:
                parts.append(f"missing key(s): {', '.join(missing)}")
            if unknown:
                parts.append(f"unknown key(s): {', '.join(unknown)}")
            fail("B2", f"line {number}: {'; '.join(parts)}")
        for key in CORRECTION_KEYS:
            if not isinstance(entry[key], str):
                fail("B2", f"line {number}: value for {key} is not a string")
        date = entry["date"]
        if CORRECTIONS_DATE.match(date) is None:
            fail("B2", f"line {number}: invalid date: {date}")
        year, month, day = (int(part) for part in date.split("-"))
        try:
            datetime.date(year, month, day)
        except ValueError:
            fail("B2", f"line {number}: invalid date: {date}")
        for key in ("scope", "correction", "evidence"):
            if entry[key].strip() == "":
                fail("B2", f"line {number}: {key} is empty")


def check_b4(root):
    """The Makefile has verify, check and ci, ci runs verify, mise pins the tools."""
    text = read(root, "Makefile")
    if text is None:
        fail("B4", "Makefile is missing")
    rules = {}
    for line in text.splitlines():
        match = re.match(r"^([\w-]+):\s*([^=#]*)(?:#.*)?$", line)
        if match:
            rules[match.group(1)] = match.group(2).split()
    for target in ("verify", "check", "ci"):
        if target not in rules:
            fail("B4", f"the Makefile has no {target} rule")
    if "verify" not in rules["ci"]:
        fail("B4", f"ci depends on {rules['ci'] or 'nothing'}, not on verify")
    for name in ("mise.toml", "mise.lock"):
        if not (Path(root) / name).is_file():
            fail("B4", f"{name} is missing")


def check_b5(root):
    """Least privilege: read-only top-level permissions, no persisted credentials, SHA pins.

    Every `uses:` that names an action or a reusable workflow is a 40-character
    commit SHA with a version comment after it (core ADR-0021). A local action,
    which starts with `./`, is exempt.
    """
    files = workflows(root)
    if not files:
        fail("B5", "there is no .github/workflows/*.yml")
    for path, text in files:
        value, granted = top_permissions(text)
        if value is None:
            fail("B5", f"{path.name} has no top-level permissions")
        if value not in ("{}", ""):
            fail("B5", f"{path.name} has the top-level permissions {value}")
        if value == "":
            if not granted:
                fail("B5", f"{path.name} has a top-level permissions key with no value")
            for scope, level in granted:
                if level not in ("read", "none"):
                    fail("B5", f"{path.name} grants {scope}: {level} at the top level")
        lines = text.split("\n")
        for number, line in enumerate(lines):
            if not LIST_ITEM.match(line):
                continue
            block = "\n".join(indented_block(lines, number))
            if "actions/checkout" not in block:
                continue
            if not re.search(r"^\s*persist-credentials:\s*false\s*$", block, re.M):
                fail("B5", f"{path.name} line {number + 1}: a checkout does not set persist-credentials: false")
        for number, line in enumerate(lines, start=1):
            match = USES.search(line)
            if not match:
                continue
            reference = match.group(1).strip("'\"")
            if reference.startswith("./"):
                continue
            action, at, ref = reference.partition("@")
            if not at or re.fullmatch(r"[0-9a-f]{40}", ref) is None:
                fail("B5", f"{path.name} line {number}: {reference} is not a 40-character commit SHA")
            if "#" not in line.split(reference, 1)[1]:
                fail("B5", f"{path.name} line {number}: the pin of {action} has no version comment")


def expand_braces(glob):
    """The expansions of a glob's brace groups, and the spec's errors on them."""
    parts = []
    errors = []
    literal = ""
    index = 0
    while index < len(glob):
        char = glob[index]
        if char == "}":
            errors.append("unmatched '}'")
            index += 1
            continue
        if char != "{":
            literal += char
            index += 1
            continue
        close = glob.find("}", index + 1)
        next_open = glob.find("{", index + 1)
        if close == -1:
            errors.append("unmatched '{'")
            break
        if next_open != -1 and next_open < close:
            errors.append("nested braces are not supported")
            break
        alternatives = glob[index + 1:close].split(",")
        if len(alternatives) < 2:
            errors.append("a brace group needs at least 2 alternatives")
        if any(alternative == "" for alternative in alternatives):
            errors.append("a brace group has an empty alternative")
        parts.append([literal])
        parts.append(alternatives)
        literal = ""
        index = close + 1
    if errors:
        return [], errors
    parts.append([literal])
    expansions = [""]
    for alternatives in parts:
        expansions = [prefix + alternative for prefix in expansions for alternative in alternatives]
        if len(expansions) > MAX_BRACE_EXPANSIONS:
            return [], [f"brace expansion gives more than {MAX_BRACE_EXPANSIONS} globs"]
    return expansions, []


def validate_glob(glob):
    """The risk-paths spec's glob syntax rules; the list of problems is empty when valid."""
    if not isinstance(glob, str):
        return ["glob is not a string"]
    if glob == "":
        return ["glob is empty"]
    errors = [f"{char!r} is not supported" for char in ("[", "]", "!", "\\") if char in glob]
    expansions, brace_errors = expand_braces(glob)
    errors.extend(brace_errors)
    for expansion in expansions:
        if expansion.startswith("/"):
            errors.append("a glob must not start with '/'")
        if expansion.startswith("./"):
            errors.append("a glob must not start with './'")
        for segment in expansion.split("/"):
            if segment == "":
                errors.append("a glob must not have an empty segment")
            elif segment == "..":
                errors.append("a glob must not have a '..' segment")
            elif "**" in segment and segment != "**":
                errors.append("'**' must be a whole segment")
    return sorted(set(errors))


def segment_pattern(segment):
    """1 glob segment as a pattern: `*` any run in the segment, `?` 1 character."""
    source = ""
    for char in segment:
        if char == "*":
            source += "[^/]*"
        elif char == "?":
            source += "[^/]"
        else:
            source += re.escape(char)
    return re.compile(source)


def match_segments(glob_segments, path_segments):
    """Whole-segment match: `**` matches 0 or more whole segments."""
    if not glob_segments:
        return not path_segments
    if glob_segments[0] == "**":
        return match_segments(glob_segments[1:], path_segments) or (
            bool(path_segments) and match_segments(glob_segments, path_segments[1:])
        )
    if not path_segments:
        return False
    return (segment_pattern(glob_segments[0]).fullmatch(path_segments[0]) is not None
            and match_segments(glob_segments[1:], path_segments[1:]))


def match(glob, path):
    """Match a path against a risk-path glob, as core's matchGlob does.

    `*` matches any run of characters in 1 segment, `?` matches 1 character in
    1 segment, `**` as a whole segment matches 0 or more segments, and a brace
    group matches 1 of its alternatives. The whole path must match.
    """
    if not isinstance(glob, str) or not isinstance(path, str) or glob == "" or path == "":
        return False
    expansions, errors = expand_braces(glob)
    if errors:
        return False
    path_segments = path.split("/")
    return any(match_segments(expansion.split("/"), path_segments) for expansion in expansions)


def strict_object(pairs):
    """A JSON object that refuses a duplicate key, as core's parseStrictJson does."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r}")
        result[key] = value
    return result


def check_b6(root):
    """.github/risk-paths.json, schema version 2 by the risk-paths spec, and the caller workflow."""
    text = read(root, RISK_LIST)
    if text is None:
        fail("B6", f"{RISK_LIST} is missing")
    try:
        document = json.loads(text, object_pairs_hook=strict_object)
    except ValueError as error:
        fail("B6", f"{RISK_LIST} is not JSON: {error}")
    if not isinstance(document, dict):
        fail("B6", "$: the top level must be an object")
    unknown = sorted(set(document) - set(LIST_KEYS))
    missing = sorted(set(LIST_KEYS) - set(document))
    if unknown:
        fail("B6", f"$: unknown key(s): {', '.join(unknown)}")
    if missing:
        fail("B6", f"$: missing key(s): {', '.join(missing)}")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        fail("B6", f"schema_version: must be the integer {SCHEMA_VERSION}")
    default_level = document["default_level"]
    if not isinstance(default_level, str) or default_level not in LEVELS:
        fail("B6", f"default_level: must be 1 of {', '.join(LEVELS)}")
    entries = document["paths"]
    if not isinstance(entries, list):
        fail("B6", "paths: must be an array")
    if not entries:
        fail("B6", "paths: must have at least 1 entry")
    globs = {}
    for index, entry in enumerate(entries):
        at = f"paths[{index}]"
        if not isinstance(entry, dict):
            fail("B6", f"{at}: must be an object")
        unknown = sorted(set(entry) - set(ENTRY_KEYS))
        missing = sorted(set(ENTRY_KEYS) - set(entry))
        if unknown:
            fail("B6", f"{at}: unknown key(s): {', '.join(unknown)}")
        if missing:
            fail("B6", f"{at}: missing key(s): {', '.join(missing)}")
        glob = entry["glob"]
        if not isinstance(glob, str):
            fail("B6", f"{at}.glob: must be a string")
        problems = validate_glob(glob)
        if problems:
            fail("B6", f"{at}.glob: {glob!r}: {problems[0]}")
        if glob in globs:
            fail("B6", f"{at}.glob: duplicate glob {glob!r} (also paths[{globs[glob][0]}])")
        level = entry["level"]
        if not isinstance(level, str) or level not in LEVELS:
            fail("B6", f"{at}.level: must be 1 of {', '.join(LEVELS)}")
        globs[glob] = (index, level)
        why = entry["why"]
        if not isinstance(why, str):
            fail("B6", f"{at}.why: must be a string")
        if why.strip() == "":
            fail("B6", f"{at}.why: must not be empty")
        if len(why) > MAX_WHY_LENGTH:
            fail("B6", f"{at}.why: must be at most {MAX_WHY_LENGTH} characters")
        if not WHY_CATEGORY.match(why):
            fail("B6", f"{at}.why: does not name a category of the spec")
    for required in REQUIRED_RISK_PATHS:
        if not any(match(glob, required) for glob in globs):
            fail("B6", f"no glob matches {required}")
    if not any(match(glob, CALLER) for glob in globs):
        fail("B6", f"no glob matches the caller workflow {CALLER}")
    for required in (RISK_LIST, CALLER):
        for glob, (_, level) in globs.items():
            if match(glob, required) and level not in STRICT_LEVELS:
                fail("B6", f"the glob {glob!r} matches {required} and must be L1 or L2, not {level}")
    caller = next(((path, text) for path, text in workflows(root) if CORE_PR_TRIAGE.search(text)), None)
    if caller is None:
        fail("B6", "no workflow calls frostyard/core/.github/workflows/pr-triage.yml at a commit SHA")
    path, caller_text = caller
    if "pull_request_target" not in workflow_events(caller_text):
        fail("B6", f"{path.name} does not run on pull_request_target")
    value, _ = top_permissions(caller_text)
    if value != "{}":
        fail("B6", f"{path.name} does not set top-level permissions: {{}}")
    names = caller_types(caller_text)
    if names is None:
        fail("B6", f"{path.name} has no on: pull_request_target: trigger")
    if "labeled" not in names:
        fail("B6", f"{path.name} does not list the type labeled under on: pull_request_target")
    blocks = job_blocks(caller_text)
    if CALLER_JOB not in blocks:
        fail("B6", f"{path.name} has no job named {CALLER_JOB}")
    uses = job_uses(blocks[CALLER_JOB])
    if uses is None:
        fail("B6", f"{path.name}: the job {CALLER_JOB} must set uses: at indent 4 to "
                   f"frostyard/core/.github/workflows/pr-triage.yml at a commit SHA; a uses: "
                   f"line in another job or in a run: block does not count")
    if not PINNED_USES.fullmatch(uses):
        fail("B6", f"{path.name}: the uses: of the job {CALLER_JOB} must be "
                   f"frostyard/core/.github/workflows/pr-triage.yml@<40-character commit SHA>, "
                   f"not {uses!r}")


def check_b7(root):
    """.github/pull_request_template.md has a risk tier section and names the gates."""
    text = read(root, ".github/pull_request_template.md")
    if text is None:
        fail("B7", ".github/pull_request_template.md is missing")
    if not re.search(r"(?m)^#{1,6} .*Risk tier", text):
        fail("B7", "the pull request template has no Risk tier heading")
    for command in ("make verify", "make ci"):
        if command not in text:
            fail("B7", f"the pull request template does not name {command}")


def check_b10(root):
    """LICENSE is the MIT license or GPL-3.0.

    The license metadata that GitHub reports (`gh api repos/<owner>/<repo>
    --jq .license.spdx_id`) is outside this check: the tree cannot show it.
    """
    text = read(root, "LICENSE")
    if text is None:
        fail("B10", "LICENSE is missing")
    if "MIT License" in text:
        return
    if re.search(r"GNU GENERAL PUBLIC LICENSE\s+Version 3", text):
        return
    fail("B10", "LICENSE is neither the MIT license nor GPL-3.0")


def check_b12(root):
    """ci.yml runs make ci on pull_request, and no if: disables the job or the step."""
    text = read(root, ".github/workflows/ci.yml")
    if text is None:
        fail("B12", ".github/workflows/ci.yml is missing")
    events = workflow_events(text)
    if "pull_request" not in events:
        fail("B12", f"ci.yml runs on {events or 'nothing'}, not on pull_request")
    blocks = job_blocks(text)
    found = [name for name, lines in blocks.items() if any(RUN_MAKE_CI.match(line) for line in lines)]
    if not found:
        fail("B12", "ci.yml has no run: make ci step")
    for name in found:
        lines = blocks[name]
        if any(JOB_IF.match(line) for line in lines):
            fail("B12", f"the job {name} has an if: condition")
        for number, line in enumerate(lines):
            if not RUN_MAKE_CI.match(line):
                continue
            start = number
            while start >= 0 and not LIST_ITEM.match(lines[start]):
                start -= 1
            if start >= 0 and any(STEP_IF.match(step) for step in indented_block(lines, start)):
                fail("B12", f"the run: make ci step in {name} has an if: condition")


def check_b13(root):
    """.github/dependabot.yml has a github-actions entry."""
    text = read(root, ".github/dependabot.yml")
    if text is None:
        fail("B13", ".github/dependabot.yml is missing")
    if not re.search(r"(?m)^\s*-?\s*package-ecosystem:\s*[\"']?github-actions[\"']?\s*$", text):
        fail("B13", "dependabot.yml has no github-actions entry")


def check_b14(root):
    """SECURITY.md names private vulnerability reporting and the versions that get fixes."""
    text = read(root, "SECURITY.md") or read(root, ".github/SECURITY.md")
    if text is None:
        fail("B14", "SECURITY.md is missing")
    if "https://github.com/frostyard/homebrew-tap/security" not in text:
        fail("B14", "SECURITY.md does not link https://github.com/frostyard/homebrew-tap/security")
    if "private vulnerability reporting" not in text.lower():
        fail("B14", "SECURITY.md does not name private vulnerability reporting")
    if "fixes" not in text.lower():
        fail("B14", "SECURITY.md does not say which versions get fixes")


def check_b15(root):
    """No CODEOWNERS at the root, in .github/ or in docs/."""
    for name in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        if os.path.lexists(Path(root) / name):
            fail("B15", f"{name} exists")


def check_b16(root):
    """No leftover agent-framework trees, and .claude/ holds only its 3 names."""
    for name in FRAMEWORK_TREES:
        if os.path.lexists(Path(root) / name):
            fail("B16", f"{name} exists")
    claude = Path(root) / ".claude"
    if claude.is_dir():
        for child in sorted(claude.iterdir()):
            if child.name not in ("settings.json", "skills", "session-summary.md"):
                fail("B16", f".claude/{child.name} is not allowed")


def analyze_readme(text):
    """The lines, headings and top block of a README, with fenced code marked."""
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    fence = None
    for number, line in enumerate(body.split("\n"), start=1):
        trimmed = line.strip()
        start = README_FENCE.match(trimmed)
        entry = {"number": number, "text": line, "in_fence": False, "is_fence": False}
        if fence is not None:
            if start and trimmed.startswith(fence):
                entry["is_fence"] = True
                fence = None
            else:
                entry["in_fence"] = True
        elif start:
            entry["is_fence"] = True
            fence = start.group(1)
        lines.append(entry)
    content = [entry for entry in lines if not entry["in_fence"] and not entry["is_fence"]]
    headings = []
    for entry in content:
        match = README_HEADING.match(entry["text"])
        if match:
            headings.append({"number": entry["number"], "level": len(match.group(1)), "text": match.group(2).strip()})
    first_h2 = next((heading for heading in headings if heading["level"] == 2), None)
    top = [entry for entry in lines if first_h2 is None or entry["number"] < first_h2["number"]]
    return {"text": body, "lines": lines, "content": content, "headings": headings, "top": top}


def link_targets(text):
    """Every link destination in one line."""
    return README_INLINE_LINK.findall(text) + README_AUTOLINK.findall(text)


def badge_allowed(image):
    """The README spec's list of allowed badge sources."""
    url = urllib.parse.urlsplit(image)
    host = url.hostname.lower() if url.hostname else ""
    if host == "github.com":
        return re.search(r"/actions/workflows/[^/]+/badge\.svg", url.path) is not None
    if host in README_BADGE_HOSTS:
        return True
    if host == "pkg.go.dev":
        return url.path.startswith("/badge/")
    if host == "img.shields.io":
        return url.path.startswith("/github/v/release/")
    return False


def check_readme_rules(root, text):
    """The README spec's rules R1 to R12, except R12's emoji rule."""
    document = analyze_readme(text)
    lines = document["lines"]
    headings = document["headings"]
    top = document["top"]

    def content(entry):
        return not entry["in_fence"] and not entry["is_fence"]

    def is_comment(entry):
        return entry["text"].strip().startswith("<!--")

    def is_image(entry):
        return "<img" in entry["text"].lower() or entry["text"].strip().startswith("![")

    def is_badge(entry):
        return "[![" in entry["text"]

    def is_heading(entry):
        return README_HEADING.match(entry["text"]) is not None

    # R1 — the kind marker.
    markers = [entry for entry in lines if content(entry) and README_MARKER.match(entry["text"].strip())]
    kind = None
    if len(markers) != 1:
        fail("B17", f"R1: expected exactly 1 readme-kind marker, found {len(markers)}")
    kind = README_MARKER.match(markers[0]["text"].strip()).group(1)
    if kind not in README_KINDS:
        fail("B17", f"R1: unknown kind {kind!r} on line {markers[0]['number']}")

    # R2 — 1 level-1 title, first.
    if not headings:
        fail("B17", "R2: no heading: the README needs 1 level-1 title")
    if headings[0]["level"] != 1:
        fail("B17", f"R2: the first heading {headings[0]['text']!r} on line {headings[0]['number']} is not level 1")
    titles = [heading for heading in headings if heading["level"] == 1]
    if len(titles) != 1:
        fail("B17", f"R2: expected exactly 1 level-1 heading, found {len(titles)}")

    # R3 — the top block: a lead before the status line, at most 130 words.
    statuses = [entry for entry in top if content(entry) and entry["text"].strip().startswith(README_STATUS_PREFIX)]
    first_status = statuses[0]["number"] if statuses else None
    lead = [entry for entry in top
            if content(entry) and entry["text"].strip() != "" and not is_comment(entry)
            and not is_image(entry) and not is_badge(entry) and not is_heading(entry)
            and not entry["text"].strip().startswith(README_STATUS_PREFIX)
            and not entry["text"].strip().startswith(README_DOC_PREFIX)
            and not README_TAGLINE.match(entry["text"].strip())]
    if statuses and not any(entry["number"] < first_status for entry in lead):
        fail("B17", "R3: the top block has no lead paragraph before the status line")
    top_words = sum(len(entry["text"].split()) for entry in top
                    if not is_comment(entry) and not is_image(entry) and not is_badge(entry)
                    and not is_heading(entry))
    if top_words > 130:
        fail("B17", f"R3: the top block has {top_words} words (at most 130)")

    # R4 — 1 status line with a known value, at most 40 words.
    if len(statuses) != 1:
        fail("B17", f"R4: expected exactly 1 {README_STATUS_PREFIX} line in the top block, found {len(statuses)}")
    status = statuses[0]["text"].strip()[len(README_STATUS_PREFIX):].strip().lower()
    value = next((candidate for candidate in README_STATUS
                  if status.startswith(candidate)
                  and (len(status) == len(candidate) or re.match(r"^[.,;:\s-]", status[len(candidate):]))), None)
    if value is None:
        fail("B17", f"R4: line {statuses[0]['number']}: the status is not 1 of {', '.join(README_STATUS)}")
    if len(statuses[0]["text"].split()) > 40:
        fail("B17", f"R4: line {statuses[0]['number']}: the status line has more than 40 words")

    # R5 — 1 documentation line with a link.
    docs = [entry for entry in top if content(entry) and entry["text"].strip().startswith(README_DOC_PREFIX)]
    if len(docs) != 1:
        fail("B17", f"R5: expected exactly 1 {README_DOC_PREFIX} line in the top block, found {len(docs)}")
    rest = docs[0]["text"].strip()[len(README_DOC_PREFIX):]
    if not link_targets(rest):
        fail("B17", f"R5: line {docs[0]['number']}: the documentation line has no link")
    if kind == "library":
        hosts = [urllib.parse.urlsplit(target).hostname for target in link_targets(rest)]
        if "pkg.go.dev" not in hosts:
            fail("B17", f"R5: line {docs[0]['number']}: a library links https://pkg.go.dev/")

    # R6 — at most 3 badges, in the top block, from the allowed sources.
    badges = 0
    for entry in document["content"]:
        at = entry["text"].find("[![")
        while at != -1:
            match = README_BADGE.match(entry["text"], at)
            if not match:
                fail("B17", f"R6: line {entry['number']}: '[![' is not a full [![alt](image)](link) badge")
            badges += 1
            if not any(line is entry for line in top):
                fail("B17", f"R6: line {entry['number']}: the badge is outside the top block")
            if not badge_allowed(match.group(1)):
                fail("B17", f"R6: line {entry['number']}: the badge image {match.group(1)} is not an allowed source")
            at = entry["text"].find("[![", at + 3)
    if badges > 3:
        fail("B17", f"R6: there are {badges} badges (at most 3)")

    # R7 — the level-2 headings match the kind's sections table.
    sections = README_KINDS[kind]
    names = sections["required"] + sections["optional"] + README_COMMON_OPTIONAL + README_LAST
    level2 = [heading for heading in headings if heading["level"] == 2]
    matched = []
    for heading in level2:
        best = None
        for name in names:
            if heading["text"].lower().startswith(name.lower()) and (best is None or len(name) > len(best)):
                best = name
        if best is None:
            fail("B17", f"R7: line {heading['number']}: the heading {heading['text']!r} matches no section of a {kind}")
        matched.append(best)
    if matched.count("Develop") != 1 or matched.index("Develop") != len(matched) - 2:
        fail("B17", "R7: 'Develop' must be the second-to-last section and appear once")
    if matched.count("Where to go next") != 1 or matched.index("Where to go next") != len(matched) - 1:
        fail("B17", "R7: 'Where to go next' must be the last section and appear once")
    seen = [name for name in matched if name in sections["required"]]
    if seen != sections["required"]:
        fail("B17", f"R7: the required sections of a {kind} are {sections['required']}, found {seen}")

    # R8 — no heading deeper than level 2.
    for heading in headings:
        if heading["level"] >= 3:
            fail("B17", f"R8: line {heading['number']}: the heading {heading['text']!r} is level {heading['level']}")

    # R9 — Develop has a fenced code line with a make gate.
    develop = next((heading for heading in level2 if heading["text"].lower().startswith("develop")), None)
    if develop is None:
        fail("B17", "R9: there is no Develop section")
    after = [heading["number"] for heading in level2 if heading["number"] > develop["number"]]
    end = after[0] if after else float("inf")
    body = [entry for entry in lines if develop["number"] < entry["number"] < end]
    if not any(entry["in_fence"] and re.search(r"(^|\s)make (ci|check|verify)\b", entry["text"]) for entry in body):
        fail("B17", f"R9: the Develop section at line {develop['number']} has no fenced line with make ci, make check or make verify")

    # R10 — Where to go next links the repository files the tree has.
    last = next((heading for heading in level2 if heading["text"].lower().startswith("where to go next")), None)
    if last is None:
        fail("B17", "R10: there is no Where to go next section")
    after = [heading["number"] for heading in level2 if heading["number"] > last["number"]]
    end = after[0] if after else float("inf")
    targets = set()
    for entry in lines:
        if not content(entry) or not last["number"] < entry["number"] < end:
            continue
        for target in README_INLINE_LINK.findall(entry["text"]):
            target = target.split("#")[0]
            if target.startswith("./"):
                target = target[2:]
            targets.add(target)
    for name in ("AGENTS.md", "docs/README.md", "SECURITY.md", ".github/SECURITY.md", "LICENSE"):
        if os.path.exists(Path(root) / name) and name not in targets:
            fail("B17", f"R10: the Where to go next section does not link {name}")

    # R11 — at most 1000 words, counted as the checker counts them.
    words = len(document["text"].split())
    if words > 1000:
        fail("B17", f"R11: the README has {words} words (at most 1000)")

    # R12 — no private address, at most 2 dates outside fenced code, no tree drawing.
    for match_v4 in README_PRIVATE_V4.finditer(document["text"]):
        line = document["text"].count("\n", 0, match_v4.start()) + 1
        fail("B17", f"R12: private IPv4 address {match_v4.group(0)} at line {line}")
    dates = sum(len(README_ISO_DATE.findall(entry["text"])) for entry in document["content"])
    if dates > 2:
        fail("B17", f"R12: there are {dates} dates in YYYY-MM-DD form outside fenced code (at most 2)")
    for entry in lines:
        if "├──" in entry["text"] or "└──" in entry["text"]:
            fail("B17", f"R12: line {entry['number']}: tree drawing")


def check_b17(root):
    """README.md follows the README spec for its kind (rules R1 to R12, except R12's emoji)."""
    text = read(root, "README.md")
    if text is None:
        fail("B17", "README.md is missing")
    check_readme_rules(root, text)


CHECKS = {
    "B1": check_b1,
    "B2": check_b2,
    "B4": check_b4,
    "B5": check_b5,
    "B6": check_b6,
    "B7": check_b7,
    "B10": check_b10,
    "B12": check_b12,
    "B13": check_b13,
    "B14": check_b14,
    "B15": check_b15,
    "B16": check_b16,
    "B17": check_b17,
}

IGNORED = (".git", "__pycache__")


def copy_tree():
    """A copy of this repository outside it, with a cleanup, for a negative test."""
    folder = Path(tempfile.mkdtemp(prefix="homebrew-tap-baseline-"))
    root = ROOT.resolve()
    if folder.resolve() == root or root in folder.resolve().parents:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError(f"refusing to copy the tree to {folder}, which is inside {root}")
    shutil.copytree(ROOT, folder, symlinks=True, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*IGNORED))
    return folder


class BaselineTest(unittest.TestCase):
    def test_every_row_passes(self):
        for row, check in CHECKS.items():
            with self.subTest(row=row):
                try:
                    check(ROOT)
                except BaselineError as error:
                    self.fail(str(error))


class CorrectionsTest(unittest.TestCase):
    """B2 on a tree of its own: the rules of core's check-corrections.mjs."""

    def corrections(self, body):
        folder = Path(tempfile.mkdtemp(prefix="homebrew-tap-baseline-gate-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / ".memory").mkdir()
        (folder / ".memory" / "corrections.jsonl").write_text(body, encoding="utf-8")
        return folder

    GOOD = ('{"date": "2026-11-06", "scope": "s", "correction": "c", "evidence": "e", "promoted_to": ""}\n')

    def test_an_empty_promoted_to_passes(self):
        check_b2(self.corrections(self.GOOD))

    def test_a_blank_line_fails(self):
        with self.assertRaises(BaselineError) as caught:
            check_b2(self.corrections(self.GOOD + "\n"))
        self.assertIn("B2", str(caught.exception))
        self.assertIn("blank line", str(caught.exception))

    def test_a_short_line_that_looks_blank_fails(self):
        with self.assertRaises(BaselineError) as caught:
            check_b2(self.corrections(self.GOOD + "\r\n"))
        self.assertIn("blank line", str(caught.exception))

    def test_an_invalid_date_fails(self):
        with self.assertRaises(BaselineError) as caught:
            check_b2(self.corrections(self.GOOD.replace("2026-11-06", "2026-13-45")))
        self.assertIn("invalid date", str(caught.exception))

    def test_a_duplicate_key_fails(self):
        duplicated = ('{"date": "2026-11-06", "date": "2026-11-06", "scope": "s", "correction": "c", '
                      '"evidence": "e", "promoted_to": ""}\n')
        with self.assertRaises(BaselineError) as caught:
            check_b2(self.corrections(duplicated))
        self.assertIn("duplicate key", str(caught.exception))

    def test_a_bom_fails(self):
        with self.assertRaises(BaselineError) as caught:
            check_b2(self.corrections("\ufeff" + self.GOOD))
        self.assertIn("invalid JSON", str(caught.exception))

    def test_a_file_without_a_trailing_newline_passes(self):
        check_b2(self.corrections(self.GOOD.rstrip("\n")))

    def test_an_empty_file_passes(self):
        check_b2(self.corrections(""))


class RiskPathGlobTest(unittest.TestCase):
    """match(), by core's matchGlob: whole segments, `?` 1 character, `**` 0 or more."""

    def test_a_question_mark_matches_1_character_in_its_segment(self):
        self.assertTrue(match(".github/workflows/risk-paths.ym?", ".github/workflows/risk-paths.yml"))
        self.assertFalse(match(".github/workflows/risk-paths.ym?", ".github/workflows/risk-paths.yaml"))
        self.assertFalse(match("risk-paths.ym?", "a/risk-paths.yml"))

    def test_a_leading_double_star_matches_0_directories(self):
        self.assertTrue(match("**/.github/risk-paths.json", ".github/risk-paths.json"))
        self.assertTrue(match("**/.github/risk-paths.json", "a/b/.github/risk-paths.json"))
        self.assertFalse(match("**/.github/risk-paths.json", "a/.github/other.json"))

    def test_a_double_star_matches_0_or_more_whole_segments(self):
        self.assertTrue(match("a/**", "a"))
        self.assertTrue(match("a/**", "a/b/c"))
        self.assertTrue(match("a/**/b", "a/b"))
        self.assertTrue(match("a/**/b", "a/x/y/b"))
        self.assertFalse(match("a/**/b", "a/b/c"))
        self.assertFalse(match("**", ""))


ANOTHER_JOB_CALLER = (
    'name: PR triage\n'
    'on:\n'
    '  pull_request_target:\n'
    '    types: [opened, synchronize, reopened, edited, labeled]\n'
    'permissions: {}\n'
    'jobs:\n'
    '  pr-triage:\n'
    '    runs-on: ubuntu-latest\n'
    '    permissions:\n'
    '      contents: read\n'
    '    steps:\n'
    '      - run: echo triage\n'
    '  triage:\n'
    '    permissions:\n'
    '      contents: read\n'
    '      pull-requests: write\n'
    '    uses: {pin}\n'
)

RUN_BLOCK_CALLER = (
    'name: PR triage\n'
    'on:\n'
    '  pull_request_target:\n'
    '    types: [opened, synchronize, reopened, edited, labeled]\n'
    'permissions: {}\n'
    'jobs:\n'
    '  pr-triage:\n'
    '    runs-on: ubuntu-latest\n'
    '    permissions:\n'
    '      contents: read\n'
    '    steps:\n'
    '      - run: |\n'
    '          uses: {pin}\n'
)


OTHER_TRIGGER_CALLER = (
    'name: PR triage\n'
    'on:\n'
    '  pull_request:\n'
    '    types: [labeled]\n'
    '  pull_request_target:\n'
    '    types: [opened, synchronize, reopened, edited]\n'
    'permissions: {}\n'
    'jobs:\n'
    '  pr-triage:\n'
    '    permissions:\n'
    '      contents: read\n'
    '      pull-requests: write\n'
    '    uses: {pin}\n'
)

COMMENTED_CALLER = (
    '# A note before the workflow.\n'
    'name: PR triage\n'
    'on:\n'
    '  pull_request_target:\n'
    '    types: [opened, synchronize, reopened, edited, labeled]\n'
    'permissions: {}\n'
    'jobs:\n'
    '# A note at indent 0, before the job pr-triage.\n'
    '  pr-triage:\n'
    '    permissions:\n'
    '      contents: read\n'
    '      pull-requests: write\n'
    '# A note at indent 0, inside the job and before its uses.\n'
    '  # A note at indent 2, inside the job and before its uses.\n'
    '    # A note at indent 4, just before uses.\n'
    '    uses: {pin}\n'
)

class NegativeTest(unittest.TestCase):
    """Break each row in a copy of the tree; the row's check must fail and name it."""

    def setUp(self):
        self.root = copy_tree()
        self.addCleanup(shutil.rmtree, self.root, True)

    def assert_broken(self, row):
        with self.assertRaises(BaselineError) as caught:
            CHECKS[row](self.root)
        self.assertTrue(str(caught.exception).startswith(f"{row}:"), str(caught.exception))

    def assert_broken_because(self, row, fragment):
        """The row fails and its message holds the fragment."""
        with self.assertRaises(BaselineError) as caught:
            CHECKS[row](self.root)
        message = str(caught.exception)
        self.assertTrue(message.startswith(f"{row}:"), message)
        self.assertIn(fragment, message)


    def mise_pin(self):
        """The pinned `jdx/mise-action` line in ci.yml, as it is now.

        Dependabot bumps the pin; a negative test that names a fixed SHA
        breaks on each bump, so read the pin from the file.
        """
        text = (self.root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        found = re.search(r"jdx/mise-action@([0-9a-f]{40}) (# v\S+)", text)
        self.assertIsNotNone(found, "ci.yml has no jdx/mise-action pin with a version comment")
        return found.group(0), found.group(1), found.group(2)

    def break_file(self, name, old, new):
        path = self.root / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, f"{name} does not hold {old}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_b1_a_regular_alias_file(self):
        path = self.root / "CLAUDE.md"
        path.unlink()
        path.write_text("not a symlink\n", encoding="utf-8")
        self.assert_broken("B1")

    def test_b1_an_alias_to_another_target(self):
        path = self.root / ".cursorrules"
        path.unlink()
        os.symlink("README.md", path)
        self.assert_broken("B1")

    def test_b2_a_line_with_a_missing_field(self):
        path = self.root / ".memory" / "corrections.jsonl"
        path.write_text(path.read_text(encoding="utf-8")
                        + '{"date": "2026-11-06", "scope": "x", "correction": "y"}\n', encoding="utf-8")
        self.assert_broken("B2")

    def test_b2_a_duplicate_key(self):
        path = self.root / ".memory" / "corrections.jsonl"
        path.write_text(path.read_text(encoding="utf-8")
                        + '{"date": "2026-11-06", "date": "2026-11-06", "scope": "x", "correction": "y", '
                          '"evidence": "e", "promoted_to": ""}\n', encoding="utf-8")
        self.assert_broken("B2")

    def test_b3_is_exempt_here(self):
        self.assertNotIn("B3", CHECKS)

    def test_b4_ci_that_does_not_run_verify(self):
        self.break_file("Makefile", "ci: verify", "ci: help")
        self.assert_broken("B4")

    def test_b4_verify_named_only_in_the_comment(self):
        self.break_file("Makefile", "ci: verify ## CI gate", "ci: help ## runs verify")
        self.assert_broken("B4")

    def test_b5_a_checkout_that_keeps_credentials(self):
        self.break_file(".github/workflows/ci.yml", "          persist-credentials: false\n", "")
        self.assert_broken("B5")

    def test_b5_write_permission_at_the_top_level(self):
        self.break_file(".github/workflows/ci.yml", "permissions: {}", "permissions:\n  contents: write")
        self.assert_broken("B5")

    def test_b5_an_action_on_a_tag(self):
        pin, _, comment = self.mise_pin()
        self.break_file(".github/workflows/ci.yml", pin, f"jdx/mise-action@v5 {comment}")
        self.assert_broken("B5")

    def test_b5_a_pin_without_a_version_comment(self):
        pin, sha, _ = self.mise_pin()
        self.break_file(".github/workflows/ci.yml", pin, f"jdx/mise-action@{sha}")
        self.assert_broken("B5")

    def yaml_workflow(self, old, new):
        """A copy of ci.yml as unpinned.yaml, with 1 change: B5 must read `.yaml` too."""
        text = (self.root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn(old, text)
        (self.root / ".github" / "workflows" / "unpinned.yaml").write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_b5_a_yaml_workflow_on_a_tag(self):
        pin, _, comment = self.mise_pin()
        self.yaml_workflow(pin, f"jdx/mise-action@v5 {comment}")
        self.assert_broken("B5")

    def test_b5_a_yaml_workflow_with_write_permission_at_the_top_level(self):
        self.yaml_workflow("permissions: {}", "permissions:\n  contents: write")
        self.assert_broken("B5")

    def test_b5_a_yaml_workflow_that_keeps_credentials(self):
        self.yaml_workflow("          persist-credentials: false\n", "")
        self.assert_broken("B5")

    def test_b5_the_unchanged_yaml_copy_passes(self):
        self.yaml_workflow("make ci", "make ci")
        CHECKS["B5"](self.root)

    def test_b6_a_glob_that_misses_the_bump_script(self):
        self.break_file(RISK_LIST, '"glob": ".github/scripts/**"', '"glob": ".github/scripts/*.mjs"')
        self.assert_broken("B6")

    def test_b6_a_glob_that_misses_a_cask(self):
        self.break_file(RISK_LIST, '"glob": "Casks/**"', '"glob": "casks/**"')
        self.assert_broken("B6")

    def test_b6_a_why_without_a_category(self):
        self.break_file(RISK_LIST, '"why": "governance: the verify gate"', '"why": "the verify gate"')
        self.assert_broken("B6")

    def test_b6_the_self_entry_removed(self):
        text = (self.root / RISK_LIST).read_text(encoding="utf-8")
        document = json.loads(text)
        document["paths"] = [entry for entry in document["paths"] if entry["glob"] != RISK_LIST]
        (self.root / RISK_LIST).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        self.assert_broken("B6")

    def test_b6_a_version_1_list(self):
        self.break_file(RISK_LIST, '"schema_version": 2,\n  "default_level": "L3",\n', '"schema_version": 1,\n')
        self.assert_broken("B6")

    def test_b6_a_schema_version_that_is_a_boolean(self):
        self.break_file(RISK_LIST, '"schema_version": 2,', '"schema_version": true,')
        self.assert_broken("B6")

    def test_b6_a_bad_default_level(self):
        self.break_file(RISK_LIST, '"default_level": "L3"', '"default_level": "L5"')
        self.assert_broken("B6")

    def test_b6_a_list_without_a_default_level(self):
        self.break_file(RISK_LIST, '  "default_level": "L3",\n', '')
        self.assert_broken("B6")

    def test_b6_an_entry_without_a_level(self):
        self.break_file(RISK_LIST, '      "glob": "Makefile",\n      "level": "L2",\n',
                        '      "glob": "Makefile",\n')
        self.assert_broken("B6")

    def test_b6_a_level_outside_l1_to_l4(self):
        self.break_file(RISK_LIST, '      "glob": "Makefile",\n      "level": "L2",\n',
                        '      "glob": "Makefile",\n      "level": "L5",\n')
        self.assert_broken("B6")

    def test_b6_the_list_glob_at_l3(self):
        self.break_file(RISK_LIST, '      "glob": ".github/risk-paths.json",\n      "level": "L2",\n',
                        '      "glob": ".github/risk-paths.json",\n      "level": "L3",\n')
        self.assert_broken("B6")

    def test_b6_the_caller_glob_at_l3(self):
        self.break_file(RISK_LIST, '      "glob": ".github/workflows/**",\n      "level": "L1",\n',
                        '      "glob": ".github/workflows/**",\n      "level": "L3",\n')
        self.assert_broken("B6")

    def test_b6_an_unknown_top_level_key(self):
        self.break_file(RISK_LIST, '"schema_version": 2', '"schema_version": 2,\n  "owners": []')
        self.assert_broken("B6")

    def test_b6_a_duplicate_top_level_key(self):
        self.break_file(".github/risk-paths.json", '"schema_version": 2,', '"schema_version": 2,\n  "schema_version": 2,')
        self.assert_broken("B6")

    def test_b6_a_duplicate_entry_key(self):
        self.break_file(".github/risk-paths.json", '"glob": "Makefile",', '"glob": "Makefile",\n      "glob": "Makefile",')
        self.assert_broken("B6")
        self.assert_broken("B6")

    def test_b6_a_duplicate_glob(self):
        self.break_file(RISK_LIST, '"glob": "mise.lock"', '"glob": "Makefile"')
        self.assert_broken("B6")

    def test_b6_a_bad_glob(self):
        self.break_file(RISK_LIST, '"glob": "Casks/**"', '"glob": "Casks/**.rb"')
        self.assert_broken("B6")

    def test_b6_a_why_that_is_too_long(self):
        self.break_file(RISK_LIST, '"why": "governance: the verify gate"',
                        '"why": "governance: ' + "x" * 200 + '"')
        self.assert_broken("B6")

    def test_b6_a_caller_on_pull_request(self):
        self.break_file(CALLER, "pull_request_target:", "pull_request:")
        self.assert_broken("B6")

    def test_b6_a_caller_that_still_pins_risk_paths_yml(self):
        self.break_file(CALLER, "workflows/pr-triage.yml@", "workflows/risk-paths.yml@")
        self.assert_broken("B6")

    def core_pin(self):
        """The pinned core reusable workflow of the caller, as it is now.

        A core bump changes the SHA and its date comment; a negative test that
        names a fixed SHA breaks on each bump, so read the pin from the file.
        """
        text = (self.root / CALLER).read_text(encoding="utf-8")
        found = re.search(r"frostyard/core/\.github/workflows/pr-triage\.yml@[0-9a-f]{40}", text)
        self.assertIsNotNone(found, f"{CALLER} has no pinned pr-triage.yml caller")
        return found.group(0)

    def test_b6_a_caller_on_a_core_branch(self):
        self.break_file(CALLER, self.core_pin(), "frostyard/core/.github/workflows/pr-triage.yml@main")
        self.assert_broken("B6")

    def test_b6_a_caller_without_the_labeled_type(self):
        self.break_file(CALLER, "reopened, edited, labeled]", "reopened, edited]")
        self.assert_broken("B6")

    def test_b6_a_caller_with_another_job_id(self):
        self.break_file(CALLER, "  pr-triage:\n", "  levels:\n")
        self.assert_broken("B6")

    def test_b6_a_caller_with_the_pinned_uses_in_another_job(self):
        (self.root / CALLER).write_text(ANOTHER_JOB_CALLER.replace("{pin}", self.core_pin()),
                                        encoding="utf-8")
        self.assert_broken_because("B6", "must set uses: at indent 4")

    def test_b6_a_caller_with_the_pinned_uses_in_a_run_block(self):
        (self.root / CALLER).write_text(RUN_BLOCK_CALLER.replace("{pin}", self.core_pin()),
                                        encoding="utf-8")
        self.assert_broken_because("B6", "must set uses: at indent 4")

    def test_b6_a_caller_with_comments_before_its_uses(self):
        (self.root / CALLER).write_text(COMMENTED_CALLER.replace("{pin}", self.core_pin()),
                                        encoding="utf-8")
        check_b6(self.root)

    def add_risk_entry(self, entry):
        """Add 1 entry to a copy of the risk-path list."""
        path = self.root / RISK_LIST
        document = json.loads(path.read_text(encoding="utf-8"))
        document["paths"].append(entry)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def test_b6_an_l3_glob_with_a_question_mark_that_matches_the_caller(self):
        self.add_risk_entry({"glob": ".github/workflows/risk-paths.ym?", "level": "L3",
                             "why": "governance: the caller"})
        self.assert_broken_because("B6", "must be L1 or L2")

    def test_b6_an_l3_glob_with_a_leading_double_star_that_matches_the_list(self):
        self.add_risk_entry({"glob": "**/.github/risk-paths.json", "level": "L3",
                             "why": "governance: the list"})
        self.assert_broken_because("B6", "must be L1 or L2")

    def test_b6_a_job_header_inside_a_run_name_block(self):
        self.break_file(CALLER, "  pr-triage:\n", "  other:\n")
        caller = self.root / CALLER
        caller.write_text(
            caller.read_text(encoding="utf-8")
            + "run-name: |\n"
            + "  pr-triage:\n"
            + f"    uses: {self.core_pin()}\n",
            encoding="utf-8")
        self.assert_broken_because("B6", "has no job named pr-triage")

    def test_b6_a_types_list_of_another_trigger(self):
        (self.root / CALLER).write_text(OTHER_TRIGGER_CALLER.replace("{pin}", self.core_pin()),
                                        encoding="utf-8")
        self.assert_broken_because("B6", "does not list the type labeled under on: pull_request_target")


    def test_b7_a_template_without_a_risk_tier(self):
        self.break_file(".github/pull_request_template.md", "## Risk tier", "## Risks")
        self.assert_broken("B7")

    def test_b10_a_missing_license(self):
        (self.root / "LICENSE").unlink()
        self.assert_broken("B10")

    def test_b12_an_event_that_is_not_pull_request(self):
        self.break_file(".github/workflows/ci.yml", "  pull_request:", "  pull_request_target:")
        self.assert_broken("B12")

    def test_b12_an_event_key_that_only_contains_the_name(self):
        self.break_file(".github/workflows/ci.yml", "  pull_request:", "  push:")
        self.assert_broken("B12")

    def test_b12_an_if_false_on_the_job(self):
        self.break_file(".github/workflows/ci.yml", "  test:\n", "  test:\n    if: false\n")
        self.assert_broken("B12")

    def test_b12_an_if_false_as_the_first_key_of_the_step(self):
        self.break_file(".github/workflows/ci.yml", "      - run: make ci", "      - if: false\n        run: make ci")
        self.assert_broken("B12")

    def test_b12_an_if_false_on_the_step(self):
        self.break_file(".github/workflows/ci.yml", "      - run: make ci", "      - run: make ci\n        if: false")
        self.assert_broken("B12")

    def test_b12_ci_without_make_ci(self):
        self.break_file(".github/workflows/ci.yml", "- run: make ci", "- run: python3 -m unittest discover -s .github/scripts")
        self.assert_broken("B12")

    def test_b13_a_dependabot_without_the_actions_entry(self):
        self.break_file(".github/dependabot.yml", '"github-actions"', '"gomod"')
        self.assert_broken("B13")

    def test_b14_a_security_policy_without_the_link(self):
        self.break_file("SECURITY.md", "https://github.com/frostyard/homebrew-tap/security",
                        "https://example.org/security")
        self.assert_broken("B14")

    def test_b15_a_codeowners_file(self):
        (self.root / "CODEOWNERS").write_text("* @frostyard/owners\n", encoding="utf-8")
        self.assert_broken("B15")

    def test_b16_a_framework_tree(self):
        (self.root / "docs" / "superpowers").mkdir()
        self.assert_broken("B16")

    def test_b16_a_name_in_claude(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.local.json").write_text("{}\n", encoding="utf-8")
        self.assert_broken("B16")

    def test_b17_the_title_removed(self):
        self.break_file("README.md", "# homebrew-tap\n", "")
        self.assert_broken("B17")

    def test_b17_the_status_line_removed(self):
        self.break_file("README.md", "**Status:** in production. It publishes from `main`.\n\n", "")
        self.assert_broken("B17")

    def test_b17_the_documentation_line_removed(self):
        self.break_file("README.md", "**Documentation:** [docs/README.md](docs/README.md)\n\n", "")
        self.assert_broken("B17")

    def test_b17_a_missing_required_section(self):
        self.break_file("README.md", "## What it publishes", "## The apps")
        self.assert_broken("B17")

    def test_b17_an_unknown_section(self):
        self.break_file("README.md", "## Develop", "## Usage\n\nSome text.\n\n## Develop")
        self.assert_broken("B17")

    def test_b17_develop_after_where_to_go_next(self):
        text = (self.root / "README.md").read_text(encoding="utf-8")
        start = text.index("## Develop")
        end = text.index("## Where to go next")
        moved = text[:start] + text[end:] + "\n" + text[start:end]
        (self.root / "README.md").write_text(moved, encoding="utf-8")
        self.assert_broken("B17")

    def test_b17_a_readme_over_the_word_limit(self):
        path = self.root / "README.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nword " * 1001, encoding="utf-8")
        self.assert_broken("B17")

    def test_b17_a_readme_of_another_kind(self):
        self.break_file("README.md", "<!-- readme-kind: packaging -->", "<!-- readme-kind: tool -->")
        self.assert_broken("B17")

    def test_b17_a_private_address(self):
        self.break_file("README.md", "## Install", "```sh\ncurl 192.168.1.10\n```\n\n## Install")
        self.assert_broken("B17")


class StepTest(unittest.TestCase):
    """The checkout scan finds a step by indentation, not by its first key."""

    HEAD = (
        "name: CI\n"
        "on: [pull_request]\n"
        "permissions: {}\n"
        "jobs:\n"
        "  test:\n"
        "    permissions:\n"
        "      contents: read\n"
        "    steps:\n"
    )

    def write(self, steps):
        folder = Path(tempfile.mkdtemp(prefix="homebrew-tap-baseline-steps-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / ".github" / "workflows").mkdir(parents=True)
        (folder / ".github" / "workflows" / "ci.yml").write_text(self.HEAD + steps, encoding="utf-8")
        return folder

    def test_a_step_that_starts_with_the_name(self):
        root = self.write("      - name: Checkout\n"
                          "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
                          "        with:\n"
                          "          persist-credentials: false\n")
        check_b5(root)

    def test_a_step_that_starts_with_a_bare_dash(self):
        root = self.write("      -\n"
                          "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
                          "        with:\n"
                          "          persist-credentials: false\n")
        check_b5(root)

    def test_a_step_that_starts_with_the_name_and_keeps_credentials(self):
        root = self.write("      - name: Checkout\n"
                          "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
                          "\n"
                          "      - name: Test\n"
                          "        run: make ci\n")
        with self.assertRaises(BaselineError) as caught:
            check_b5(root)
        self.assertIn("persist-credentials", str(caught.exception))

    def test_a_write_permission_below_the_top_level_is_allowed(self):
        root = self.write("      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
                          "        with:\n"
                          "          persist-credentials: false\n")
        path = root / ".github" / "workflows" / "ci.yml"
        path.write_text(path.read_text().replace("      contents: read\n", "      contents: write\n"))
        self.assertIn("contents: write", path.read_text())
        check_b5(root)


class EventTest(unittest.TestCase):
    """The `on:` forms the README of the spec names, and the ones it rejects."""

    def test_a_single_event(self):
        self.assertEqual(workflow_events("on: pull_request\njobs:\n"), ["pull_request"])

    def test_an_event_list(self):
        self.assertEqual(workflow_events("on: [push, pull_request]\njobs:\n"), ["push", "pull_request"])

    def test_a_block_mapping(self):
        text = "on:\n  pull_request:\n    branches: [main]\n  push:\n    branches: [main]\n"
        self.assertEqual(workflow_events(text), ["pull_request", "push"])

    def test_pull_request_target_is_not_pull_request(self):
        text = "on:\n  pull_request_target:\n    types: [opened]\njobs:\n"
        self.assertNotIn("pull_request", workflow_events(text))


class CopyTest(unittest.TestCase):
    def test_the_copy_is_outside_the_repository(self):
        folder = copy_tree()
        self.addCleanup(shutil.rmtree, folder, True)
        root = ROOT.resolve()
        self.assertNotEqual(folder.resolve(), root)
        self.assertNotIn(root, folder.resolve().parents)
        self.assertTrue((folder / "AGENTS.md").is_file())
        self.assertTrue((folder / "CLAUDE.md").is_symlink())
        self.assertFalse((folder / ".git").exists())


if __name__ == "__main__":
    unittest.main()
