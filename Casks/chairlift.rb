cask "chairlift" do
  arch arm: "arm64", intel: "amd64"
  os linux: "linux"

  version "0.11.4"
  sha256 arm64_linux:  "8cf61154152b367018398117818e6ad75ef1323ea25f660f98c6d18ea45081e4",
         x86_64_linux: "8a8013e837fc46a8fbc3ee2badda84cfb7e7bf59c7ba350493a1b5e0f11dcff8"

  url "https://github.com/frostyard/chairlift/releases/download/v#{version}/chairlift_#{version}_linux_#{arch}.tar.gz"
  name "ChairLift"
  desc "System management tool for bootc-based installations"
  homepage "https://github.com/frostyard/chairlift"

  livecheck do
    url :url
    strategy :github_latest
  end

  binary "chairlift"
  binary "data/chairlift-wrapper.sh", target: "chairlift-wrapper"
  artifact "data/org.frostyard.ChairLift.desktop",
           target: "#{Dir.home}/.local/share/applications/org.frostyard.ChairLift.desktop"
  artifact "data/icons/hicolor/scalable/apps/org.frostyard.ChairLift.svg",
           target: "#{Dir.home}/.local/share/icons/hicolor/scalable/apps/org.frostyard.ChairLift.svg"
  artifact "data/icons/hicolor/scalable/apps/org.frostyard.ChairLift-flower.svg",
           target: "#{Dir.home}/.local/share/icons/hicolor/scalable/apps/org.frostyard.ChairLift-flower.svg"
  artifact "data/icons/hicolor/symbolic/apps/org.frostyard.ChairLift-symbolic.svg",
           target: "#{Dir.home}/.local/share/icons/hicolor/symbolic/apps/org.frostyard.ChairLift-symbolic.svg"

  preflight_steps do
    mkdir_p ".local/share/applications", base: :home
    mkdir_p ".local/share/icons/hicolor/scalable/apps", base: :home
    mkdir_p ".local/share/icons/hicolor/symbolic/apps", base: :home

    # Point the menu entry at the brew-managed wrapper so the app inherits
    # the Homebrew environment even when the session PATH lacks brew.
    inreplace "data/org.frostyard.ChairLift.desktop",
              /^Exec=.*/,
              "Exec={{HOMEBREW_PREFIX}}/bin/chairlift-wrapper"
  end

  # chairlift-updex-helper is intentionally not linked: it requires polkit
  # policies under /usr/share/polkit-1 that a user-scope cask cannot
  # provide. See https://github.com/frostyard/chairlift/issues/54
end
