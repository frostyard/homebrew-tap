<!-- readme-kind: packaging -->
# homebrew-tap

The Frostyard Homebrew tap. It installs the binary releases of Frostyard's
Linux applications with Homebrew, and it builds the Homebrew tarball that the
Snow Linux images install. It is for people who run a Frostyard Linux image,
or another Linux host, and want 1 command to install an application.

**Status:** in production. It publishes from `main`.

**Documentation:** [docs/README.md](docs/README.md)

## What it publishes

| Item | What it is | Where it comes from |
| --- | --- | --- |
| `chairlift` cask | A system management tool for bootc-based installations | The release of [`frostyard/chairlift`](https://github.com/frostyard/chairlift). [`.github/workflows/bump.yml`](.github/workflows/bump.yml) updates the cask each day. |
| `nsl` cask | Development machines on atomic hosts | GoReleaser in [`frostyard/nsl`](https://github.com/frostyard/nsl) writes `Casks/nsl.rb` on a release. |
| Homebrew tarball | A Homebrew installation that a Snow Linux image unpacks | [`.github/workflows/brew-tarball.yml`](.github/workflows/brew-tarball.yml) builds it each Tuesday and uploads it to a GitHub release. |

## Install

Tap the repository once, then install the casks you want:

```sh
brew tap frostyard/tap
brew install --cask nsl
brew install --cask chairlift
```

Both casks install on Linux only. `nsl` needs an x86-64 host with KVM,
`systemd-vmspawn`, QEMU, UEFI firmware and `virtiofsd`, and membership in the
`kvm` group; `nsl doctor` checks the host and its caveats name the
installation guide.

## How it works

An application's release is the source of a cask's version and its sha256.
`nsl` writes its cask from GoReleaser; every other cask is updated by the
daily [bump workflow](.github/workflows/bump.yml), which downloads each new
asset, verifies its sha256, its line in the release's `checksums.txt` (when
the release has one) and its build attestation, and opens 1 pull request per cask. [brew test-bot](.github/workflows/tests.yml)
checks every pull request, the label `pr-pull` merges it with `brew pr-pull`,
and [docs/design/overview.md](docs/design/overview.md) has the flow.

## Credits

The tap is forked from [ublue-os/homebrew-tap](https://github.com/ublue-os/homebrew-tap).

## Develop

```sh
mise install   # the pinned tools: Python 3.12, from mise.toml and mise.lock
make ci        # what CI runs: the gate, make verify
```

## Where to go next

- [AGENTS.md](AGENTS.md): the rules for agents and contributors.
- [docs/README.md](docs/README.md): the documentation index and the design.
- [SECURITY.md](SECURITY.md): report a vulnerability privately, and what gets
  fixes.
- [LICENSE](LICENSE): MIT.
