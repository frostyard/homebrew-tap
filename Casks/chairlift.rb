cask "chairlift" do
  arch arm: "arm64", intel: "amd64"
  os linux: "linux"

  version "0.10.1"
  sha256 arm64_linux:  "7f91a1dca3a39fab4df3a40d54da228a6f9d167d7ddddc9457c541537180f0fb",
         x86_64_linux: "1cbce1da11984372105865e58bdb981e4e1e1a94652d877c7fd608d3e45eb0c5"

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

  preflight do
    FileUtils.mkdir_p "#{Dir.home}/.local/share/applications"
    FileUtils.mkdir_p "#{Dir.home}/.local/share/icons/hicolor/scalable/apps"
    FileUtils.mkdir_p "#{Dir.home}/.local/share/icons/hicolor/symbolic/apps"

    # Point the menu entry at the brew-managed wrapper so the app inherits
    # the Homebrew environment even when the session PATH lacks brew.
    desktop_file = "#{staged_path}/data/org.frostyard.ChairLift.desktop"
    content = File.read(desktop_file)
    content.gsub!(/^Exec=.*/, "Exec=#{HOMEBREW_PREFIX}/bin/chairlift-wrapper")
    File.write(desktop_file, content)
  end

  # chairlift-updex-helper is intentionally not linked: it requires polkit
  # policies under /usr/share/polkit-1 that a user-scope cask cannot
  # provide. See https://github.com/frostyard/chairlift/issues/54
end
