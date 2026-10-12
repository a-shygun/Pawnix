class Pawnix < Formula
  include Language::Python::Virtualenv

  desc "Keyboard-first chess client for terminals"
  homepage "https://github.com/a-shygun/Pawnix"
  version "0.1.0"
  url "https://github.com/a-shygun/Pawnix.git", tag: "v#{version}"
  head "https://github.com/a-shygun/Pawnix.git", branch: "main"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/pawnix --version")
  end
end
