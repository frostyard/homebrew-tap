#!/usr/bin/env python3
"""Unit tests for bump_casks.py: no network, no git, no brew.

Every test injects a fake ``gh`` layer (release lookups, downloads, attestation
checks) and a fake git, so the pipeline runs against fixture strings only.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

import bump_casks as bc


def make_tarball(members: dict[str, bytes]) -> bytes:
    """Return the bytes of a .tar.gz archive holding ``members``."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def digest(payload: bytes) -> str:
    """Return ``sha256:<hex>`` for payload bytes, like the GitHub API."""
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def asset(name: str, payload: bytes) -> dict:
    """Return one asset record of a release payload."""
    return {"name": name, "digest": digest(payload)}


class FakeGh:
    """A stand-in for GhClient that serves fixture releases and blobs."""

    def __init__(self, releases: dict, blobs: dict[str, bytes], fail_attestation: set[str] | None = None) -> None:
        self.releases = releases
        self.blobs = blobs
        self.fail_attestation = fail_attestation or set()
        self.calls: list[tuple[str, ...]] = []
        self.created_prs: list[dict] = []
        self.open_prs: dict[str, str] = {}
        self.attested: list[str] = []

    def release(self, slug: str, tag: str | None = None) -> dict | None:
        """Return the fixture payload for a slug and tag."""
        self.calls.append(("release", slug, tag or "latest"))
        return self.releases.get((slug, tag))

    def download(self, slug: str, tag: str, name: str, dest: Path) -> Path:
        """Write the fixture blob into ``dest`` and return its path."""
        self.calls.append(("download", slug, tag, name))
        path = dest / name
        path.write_bytes(self.blobs[name])
        return path

    def verify_attestation(self, path: Path, slug: str) -> None:
        """Accept the attestation unless the fixture names this asset."""
        self.calls.append(("attest", slug, path.name))
        if path.name in self.fail_attestation:
            raise bc.BumpError(f"build attestation of {path.name} does not verify: no attestation found")
        self.attested.append(path.name)

    def create_pr(self, slug: str, base: str, head: str, title: str, body: str) -> str:
        """Record the PR that the script would open."""
        self.calls.append(("create_pr", slug, base, head, title))
        self.created_prs.append({"slug": slug, "base": base, "head": head, "title": title, "body": body})
        return f"https://github.com/{slug}/pull/{len(self.created_prs)}"

    def open_pr(self, slug: str, head: str) -> str | None:
        """Return the fixture open PR number for a head branch, if any."""
        return self.open_prs.get(head)


class FakeGit:
    """A stand-in for git that records calls and knows its branches."""

    def __init__(self, branches: set[str] | None = None) -> None:
        self.branches = branches or set()
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: list[str], cwd: Path) -> str:
        """Record a git call; fail ``ls-remote`` for an absent branch."""
        self.calls.append(tuple(argv))
        if argv[:3] == ["ls-remote", "--exit-code", "--heads"]:
            if argv[-1] not in self.branches:
                raise RuntimeError(f"branch {argv[-1]} not found")
            return f"abc123\trefs/heads/{argv[-1]}\n"
        return ""


CHAIRLIFT_TEMPLATE = """cask "chairlift" do
  arch arm: "arm64", intel: "amd64"
  os linux: "linux"

  version "{version}"
  sha256 arm64_linux:  "{arm64}",
         x86_64_linux: "{amd64}"

  url "https://github.com/frostyard/chairlift/releases/download/v#{{version}}/chairlift_#{{version}}_linux_#{{arch}}.tar.gz"
  name "ChairLift"
  homepage "https://github.com/frostyard/chairlift"

  binary "chairlift"
  artifact "data/org.frostyard.ChairLift.desktop",
           target: "#{{Dir.home}}/.local/share/applications/org.frostyard.ChairLift.desktop"
end
"""

NSL_TEMPLATE = """cask "nsl" do
  version "{version}"

  on_linux do
    on_arm do
      sha256 "{arm64}"
      url "https://github.com/frostyard/nsl/releases/download/v#{{version}}/nsl_linux_arm64.tar.gz"
    end
    on_intel do
      sha256 "{amd64}"
      url "https://github.com/frostyard/nsl/releases/download/v#{{version}}/nsl_linux_amd64.tar.gz"
    end
  end

  name "nsl"
  homepage "https://github.com/frostyard/nsl"

  binary "nsl"
end
"""


class BumpTestCase(unittest.TestCase):
    """Shared fixture builders."""

    def setUp(self) -> None:
        """Create a temporary tap directory."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tap = Path(self._tmp.name)
        (self.tap / "Casks").mkdir()

    def write(self, name: str, text: str, directory: str = "Casks") -> Path:
        """Write one cask or formula file and return its path."""
        (self.tap / directory).mkdir(exist_ok=True)
        path = self.tap / directory / f"{name}.rb"
        path.write_text(text, encoding="utf-8")
        return path

    def run_item(self, bumper: bc.Bumper, path: Path, kind: str) -> bc.ItemResult:
        """Run one item with the script's diff output captured."""
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            result = bc.bump_item(bumper, path, kind)
        self.output = captured.getvalue()
        return result

    def bumper(self, gh: FakeGh, dry_run: bool = True, git: FakeGit | None = None) -> bc.Bumper:
        """Return a Bumper wired to the fakes; brew style is a no-op."""
        return bc.Bumper(
            tap_dir=self.tap,
            base_ref="main",
            dry_run=dry_run,
            gh=gh,
            style=lambda path: None,
            git=git or FakeGit(),
        )

    def chairlift_fixture(self, old_version: str, new_version: str):
        """Build a chairlift-style cask plus matching old and new releases."""
        old_amd64 = make_tarball({"chairlift": b"old-amd64", "data/org.frostyard.ChairLift.desktop": b"d"})
        old_arm64 = make_tarball({"chairlift": b"old-arm64", "data/org.frostyard.ChairLift.desktop": b"d"})
        new_amd64 = make_tarball({"chairlift": b"new-amd64", "data/org.frostyard.ChairLift.desktop": b"d"})
        new_arm64 = make_tarball({"chairlift": b"new-arm64", "data/org.frostyard.ChairLift.desktop": b"d"})
        checksums = (
            f"{digest(new_amd64).split(':')[1]}  chairlift_{new_version}_linux_amd64.tar.gz\n"
            f"{digest(new_arm64).split(':')[1]}  chairlift_{new_version}_linux_arm64.tar.gz\n"
        ).encode()
        text = CHAIRLIFT_TEMPLATE.format(
            version=old_version,
            amd64=digest(old_amd64).split(":")[1],
            arm64=digest(old_arm64).split(":")[1],
        )
        old_payload = {
            "tag_name": f"v{old_version}",
            "assets": [
                asset(f"chairlift_{old_version}_linux_amd64.tar.gz", old_amd64),
                asset(f"chairlift_{old_version}_linux_arm64.tar.gz", old_arm64),
            ],
        }
        new_payload = {
            "tag_name": f"v{new_version}",
            "assets": [
                asset(f"chairlift_{new_version}_linux_amd64.tar.gz", new_amd64),
                asset(f"chairlift_{new_version}_linux_arm64.tar.gz", new_arm64),
                asset("checksums.txt", checksums),
            ],
        }
        blobs = {
            f"chairlift_{new_version}_linux_amd64.tar.gz": new_amd64,
            f"chairlift_{new_version}_linux_arm64.tar.gz": new_arm64,
            "checksums.txt": checksums,
        }
        releases = {("frostyard/chairlift", None): new_payload, ("frostyard/chairlift", f"v{old_version}"): old_payload}
        return text, releases, blobs, new_payload


class CurrentTests(BumpTestCase):
    """Items that need no change."""

    def test_current_cask_reports_current_and_makes_no_write(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.11.2", "0.11.2")
        path = self.write("chairlift", text)
        result = self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertEqual(result.status, "current")
        self.assertEqual(result.current, "0.11.2")
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_latest_older_than_current_reports_current(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.9.0", "0.10.0")
        path = self.write("chairlift", text)
        releases[("frostyard/chairlift", None)] = {"tag_name": "v0.8.0", "assets": []}
        result = self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertEqual(result.status, "current")
        self.assertEqual(result.latest, "0.8.0")

    def test_version_compare_orders_dotted_versions(self) -> None:
        self.assertTrue(bc.version_less("0.9.0", "0.10.0"))
        self.assertTrue(bc.version_less("0.11.2", "0.12.0"))
        self.assertFalse(bc.version_less("0.10.0", "0.10.0"))
        self.assertFalse(bc.version_less("1.0.0", "0.99.9"))


class ReleaseHookTests(BumpTestCase):
    """Files that a release updates themselves."""

    def test_goreleaser_header_is_skipped_without_api_calls(self) -> None:
        text = (
            "# This file was generated by GoReleaser. DO NOT EDIT.\n"
            + NSL_TEMPLATE.format(version="0.11.0", arm64="a" * 64, amd64="b" * 64)
        )
        path = self.write("nsl", text)
        gh = FakeGh({}, {})
        result = self.run_item(self.bumper(gh), path, "cask")
        self.assertEqual(result.status, "release-hook")
        self.assertEqual(gh.calls, [])
        self.assertEqual(path.read_text(encoding="utf-8"), text)


class UnsupportedTests(BumpTestCase):
    """Files the script does not handle."""

    def test_file_without_release_url_is_unsupported(self) -> None:
        path = self.write("local", 'cask "local" do\n  version "1.0.0"\n  url "https://example.com/x.tar.gz"\nend\n')
        gh = FakeGh({}, {})
        result = self.run_item(self.bumper(gh), path, "cask")
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(gh.calls, [])


class StaleCaskTests(BumpTestCase):
    """Stale casks that must be bumped."""

    def test_chairlift_style_dry_run_rewrites_hashes_and_version(self) -> None:
        text, releases, blobs, new_payload = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        result = self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertEqual(result.status, "verified")
        self.assertEqual((result.current, result.latest), ("0.10.1", "0.11.2"))
        # The dry run restores the file through git; the fake records the call.
        edited = bc.edit_text(
            text,
            {
                bc.cask_hashes(text)[0]: bc.strip_digest(new_payload["assets"][1]["digest"]),
                bc.cask_hashes(text)[1]: bc.strip_digest(new_payload["assets"][0]["digest"]),
            },
            "0.10.1",
            "0.11.2",
        )
        self.assertIn('version "0.11.2"', edited)
        self.assertIn("v#{version}", edited)
        self.assertNotIn("0.10.1", edited)

    def test_nsl_layout_without_header_maps_assets_without_version(self) -> None:
        old_amd64 = make_tarball({"nsl": b"old-amd64"})
        old_arm64 = make_tarball({"nsl": b"old-arm64"})
        new_amd64 = make_tarball({"nsl": b"new-amd64"})
        new_arm64 = make_tarball({"nsl": b"new-arm64"})
        text = NSL_TEMPLATE.format(
            version="0.11.0",
            arm64=digest(old_arm64).split(":")[1],
            amd64=digest(old_amd64).split(":")[1],
        )
        path = self.write("nsl", text)
        old_payload = {
            "tag_name": "v0.11.0",
            "assets": [asset("nsl_linux_amd64.tar.gz", old_amd64), asset("nsl_linux_arm64.tar.gz", old_arm64)],
        }
        new_payload = {
            "tag_name": "v0.12.0",
            "assets": [asset("nsl_linux_amd64.tar.gz", new_amd64), asset("nsl_linux_arm64.tar.gz", new_arm64)],
        }
        blobs = {"nsl_linux_amd64.tar.gz": new_amd64, "nsl_linux_arm64.tar.gz": new_arm64}
        releases = {("frostyard/nsl", None): new_payload, ("frostyard/nsl", "v0.11.0"): old_payload}
        gh = FakeGh(releases, blobs)
        result = self.run_item(self.bumper(gh), path, "cask")
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.latest, "0.12.0")
        # The asset names carry no version, so both new names equal the old ones.
        self.assertEqual(bc.new_asset_name("nsl_linux_arm64.tar.gz", "0.11.0", "0.12.0"), "nsl_linux_arm64.tar.gz")
        self.assertIn(("download", "frostyard/nsl", "v0.12.0", "nsl_linux_arm64.tar.gz"), gh.calls)

    def test_formula_version_comes_from_the_url(self) -> None:
        old = make_tarball({"tool": b"old"})
        new = make_tarball({"tool": b"new"})
        text = (
            'class Tool < Formula\n  desc "x"\n'
            '  url "https://github.com/frostyard/tool/releases/download/v0.9.0/tool_0.9.0_linux_amd64.tar.gz"\n'
            f'  sha256 "{digest(old).split(":")[1]}"\n'
            '  def install\n    bin.install "tool"\n  end\nend\n'
        )
        path = self.write("tool", text, directory="Formula")
        releases = {
            ("frostyard/tool", None): {"tag_name": "v0.10.0", "assets": [asset("tool_0.10.0_linux_amd64.tar.gz", new)]},
            ("frostyard/tool", "v0.9.0"): {"tag_name": "v0.9.0", "assets": [asset("tool_0.9.0_linux_amd64.tar.gz", old)]},
        }
        gh = FakeGh(releases, {"tool_0.10.0_linux_amd64.tar.gz": new})
        git = FakeGit()
        result = self.run_item(self.bumper(gh, git=git), path, "formula")
        self.assertEqual(result.status, "verified")
        self.assertEqual((result.current, result.latest), ("0.9.0", "0.10.0"))
        self.assertIn(("checkout", "--", "Formula/tool.rb"), git.calls)


class FailureTests(BumpTestCase):
    """Every check must fail closed."""

    def test_unmappable_sha256_is_an_error(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text.replace(bc.cask_hashes(text)[0], "c" * 64, 1))
        with self.assertRaises(bc.BumpError) as raised:
            self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertIn("cannot map sha256", str(raised.exception))

    def test_digest_mismatch_is_an_error(self) -> None:
        text, releases, blobs, new_payload = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        new_payload["assets"][0]["digest"] = "sha256:" + "d" * 64
        with self.assertRaises(bc.BumpError) as raised:
            self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertIn("differs from release digest", str(raised.exception))

    def test_checksums_mismatch_is_an_error(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        blobs["checksums.txt"] = b"e" * 64 + b"  chairlift_0.11.2_linux_amd64.tar.gz\n"
        with self.assertRaises(bc.BumpError) as raised:
            self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertIn("checksums.txt", str(raised.exception))

    def test_attestation_failure_is_an_error(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        gh = FakeGh(releases, blobs, fail_attestation={"chairlift_0.11.2_linux_amd64.tar.gz"})
        with self.assertRaises(bc.BumpError) as raised:
            self.run_item(self.bumper(gh), path, "cask")
        self.assertIn("attestation", str(raised.exception))

    def test_missing_artifact_in_tarball_is_an_error(self) -> None:
        old_amd64 = make_tarball({"chairlift": b"old-amd64", "data/org.frostyard.ChairLift.desktop": b"d"})
        old_arm64 = make_tarball({"chairlift": b"old-arm64", "data/org.frostyard.ChairLift.desktop": b"d"})
        new_amd64 = make_tarball({"chairlift": b"new-amd64"})
        new_arm64 = make_tarball({"chairlift": b"new-arm64", "data/org.frostyard.ChairLift.desktop": b"d"})
        text = CHAIRLIFT_TEMPLATE.format(
            version="0.10.1",
            amd64=digest(old_amd64).split(":")[1],
            arm64=digest(old_arm64).split(":")[1],
        )
        path = self.write("chairlift", text)
        releases = {
            ("frostyard/chairlift", None): {
                "tag_name": "v0.11.2",
                "assets": [
                    asset("chairlift_0.11.2_linux_amd64.tar.gz", new_amd64),
                    asset("chairlift_0.11.2_linux_arm64.tar.gz", new_arm64),
                ],
            },
            ("frostyard/chairlift", "v0.10.1"): {
                "tag_name": "v0.10.1",
                "assets": [
                    asset("chairlift_0.10.1_linux_amd64.tar.gz", old_amd64),
                    asset("chairlift_0.10.1_linux_arm64.tar.gz", old_arm64),
                ],
            },
        }
        blobs = {
            "chairlift_0.11.2_linux_amd64.tar.gz": new_amd64,
            "chairlift_0.11.2_linux_arm64.tar.gz": new_arm64,
        }
        with self.assertRaises(bc.BumpError) as raised:
            self.run_item(self.bumper(FakeGh(releases, blobs)), path, "cask")
        self.assertIn("does not contain", str(raised.exception))

    def test_style_failure_restores_the_file(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)

        def failing_style(_path: Path) -> None:
            raise bc.BumpError("brew style failed: offense")

        bumper = self.bumper(FakeGh(releases, blobs))
        bumper.style = failing_style
        with self.assertRaises(bc.BumpError):
            self.run_item(bumper, path, "cask")
        self.assertEqual(path.read_text(encoding="utf-8"), text)


class PullRequestTests(BumpTestCase):
    """Real (non-dry) runs must branch, push, and open one PR into the base ref."""

    def test_opens_one_pr_into_the_base_ref(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        gh = FakeGh(releases, blobs)
        git = FakeGit()
        result = self.run_item(self.bumper(gh, dry_run=False, git=git), path, "cask")
        self.assertEqual(result.status, "bumped")
        self.assertEqual(len(gh.created_prs), 1)
        pr = gh.created_prs[0]
        self.assertEqual(pr["base"], "main")
        self.assertEqual(pr["head"], "bump/chairlift-0.11.2")
        self.assertEqual(pr["title"], "fix(cask): bump chairlift to v0.11.2")
        self.assertIn("0.10.1", pr["body"])
        joined = [" ".join(call) for call in git.calls]
        self.assertTrue(any("push --set-upstream origin bump/chairlift-0.11.2" in call for call in joined))
        self.assertFalse(any("--force" in call for call in joined))

    def test_existing_branch_is_pr_exists_and_opens_nothing(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        gh = FakeGh(releases, blobs)
        git = FakeGit(branches={"bump/chairlift-0.11.2"})
        result = self.run_item(self.bumper(gh, dry_run=False, git=git), path, "cask")
        self.assertEqual(result.status, "pr-exists")
        self.assertEqual(gh.created_prs, [])

    def test_pr_creation_failure_reports_pr_failed(self) -> None:
        text, releases, blobs, _ = self.chairlift_fixture("0.10.1", "0.11.2")
        path = self.write("chairlift", text)
        gh = FakeGh(releases, blobs)

        def failing_create(*_args, **_kwargs) -> str:
            raise RuntimeError("pull request create failed: GitHub Actions is not permitted to create pull requests")

        gh.create_pr = failing_create  # type: ignore[method-assign]
        result = self.run_item(self.bumper(gh, dry_run=False, git=FakeGit()), path, "cask")
        self.assertEqual(result.status, "pr-failed")
        self.assertIn("allow GitHub Actions to create pull requests", result.detail)
        self.assertTrue(result.failed)

    def test_summary_table_lists_every_item(self) -> None:
        table = bc.summary_table(
            [
                bc.ItemResult(item="chairlift", status="current", current="0.11.2", latest="0.11.2"),
                bc.ItemResult(item="nsl", status="release-hook", detail="generated on release"),
            ]
        )
        self.assertIn("| Item | Status |", table)
        self.assertIn("`chairlift` | current", table)
        self.assertIn("`nsl` | release-hook", table)
        self.assertNotIn("| error |", table)


if __name__ == "__main__":
    unittest.main()
