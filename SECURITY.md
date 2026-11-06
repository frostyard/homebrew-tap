# Security policy

homebrew-tap is a public repository. It publishes a Homebrew tap that
installs the binary releases of Frostyard's applications on Linux, and a
Homebrew tarball that the Snow Linux images install.

## Reporting a vulnerability

Use GitHub private vulnerability reporting:
https://github.com/frostyard/homebrew-tap/security

Open the Security tab and click **Report a vulnerability**.

Do not open a public issue with the details of a vulnerability. Do not post
credentials in an issue, a pull request or a discussion.

Tell us what you can: the affected commit or cask version, what an attacker
can do, and the smallest way to reproduce it. We will answer with what we
found and when a fix lands.

If a credential may be exposed, say so in the first line.

## Supported versions

The tap itself has no versions. `main` is what `brew tap frostyard/tap`
reads, and fixes land on `main`; only the current `main` gets fixes. Each cask
names a version of an application, and that application comes from its own
repository's release and is supported by that repository.

The only releases in this repository are the weekly Homebrew tarballs
(`homebrew-<date>`) that `brew-tarball.yml` makes. Only the latest tarball gets
fixes: a fix reaches it through `main` and the next tarball build. An older
tarball release keeps its assets and gets no fix.

## Scope

In scope:

- the casks in [`Casks/`](Casks/): the download URL and the sha256 of each
  cask, so that an install fetches the asset that the application's release
  published;
- [`.github/scripts/bump_casks.py`](.github/scripts/bump_casks.py) and its
  verification: the sha256 against the release digest, the line in the
  release's `checksums.txt`, and the build attestation of the artifact at the
  release tag;
- the workflows in [`.github/workflows/`](.github/workflows/) and the token
  permissions they grant: the bump, the `brew pr-pull` publish, `brew
  test-bot`, the CI gate and the risk-paths caller;
- the Homebrew tarball release that
  [`.github/workflows/brew-tarball.yml`](.github/workflows/brew-tarball.yml)
  builds and uploads: the install script it fetches and the archive that the
  images install.

Out of scope: an application's own bugs and the contents of its release. Report
those to the application's repository.
