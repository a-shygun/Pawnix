class Pawnix < Formula
  include Language::Python::Virtualenv

  desc "Keyboard-first chess client for terminals"
  homepage "https://github.com/a-shygun/Pawnix"
  version "0.1.0"
  url "https://github.com/a-shygun/Pawnix.git", tag: "v#{version}"
  head "https://github.com/a-shygun/Pawnix.git", branch: "main"
  license "MIT"

  depends_on "python@3.13"

  pypi_packages package_name: "pawnix"

  resource "keyring" do
    url "https://files.pythonhosted.org/packages/81/db/e655086b7f3a705df045bf0933bdd9c2f79bb3c97bfef1384598bb79a217/keyring-25.7.0-py3-none-any.whl"
    sha256 "be4a0b195f149690c166e850609a477c532ddbfbaed96a404d4e43f8d5e2689f"
  end

  resource "python-chess" do
    url "https://files.pythonhosted.org/packages/38/47/dfebc06e589530691d33c71bc7b3d8d311252b58ae338980fd4327fe77f2/python_chess-1.999-py3-none-any.whl"
    sha256 "93b562f8f1124cb7bf56fb095e18743758e69dc6a028ccda0badcaa5c59d88c8"
  end

  resource "chess" do
    url "https://files.pythonhosted.org/packages/93/09/7d04d7581ae3bb8b598017941781bceb7959dd1b13e3ebf7b6a2cd843bc9/chess-1.11.2.tar.gz"
    sha256 "a8b43e5678fdb3000695bdaa573117ad683761e5ca38e591c4826eba6d25bb39"
  end

  resource "jaraco.classes" do
    url "https://files.pythonhosted.org/packages/7f/66/b15ce62552d84bbfcec9a4873ab79d993a1dd4edb922cbfccae192bd5b5f/jaraco.classes-3.4.0-py3-none-any.whl"
    sha256 "f662826b6bed8cace05e7ff873ce0f9283b5c924470fe664fff1c2f00f581790"
  end

  resource "jaraco.context" do
    url "https://files.pythonhosted.org/packages/f2/58/bc8954bda5fcda97bd7c19be11b85f91973d67a706ed4a3aec33e7de22db/jaraco_context-6.1.2-py3-none-any.whl"
    sha256 "bf8150b79a2d5d91ae48629d8b427a8f7ba0e1097dd6202a9059f29a36379535"
  end

  resource "jaraco.functools" do
    url "https://files.pythonhosted.org/packages/02/36/ecc85bc96c273dc8a11273ed4782272975e6338d4a3e9228621175edf0e3/jaraco_functools-4.6.0-py3-none-any.whl"
    sha256 "99e3dc0060c5cbe8fcd1cdb36258e2a65ca40f1566b2033b12abb1bb44dd3c30"
  end

  resource "more-itertools" do
    url "https://files.pythonhosted.org/packages/e8/3d/1087453384dbde46a8c7f9356eead2c58be8a7bf156bca40243377c85715/more_itertools-11.1.0-py3-none-any.whl"
    sha256 "4b65538ae22f6fed0ce4874efd317463a7489796a0939fa66824dd542125a192"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/pawnix --version")
  end
end
