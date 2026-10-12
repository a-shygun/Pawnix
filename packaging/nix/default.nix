{
  buildPythonApplication,
  lib,
  chess,
  keyring,
  setuptools,
}:
buildPythonApplication (final: {
  pname = "pawnix";
  version = (lib.importTOML ../../pyproject.toml).project.version;
  pyproject = true;
  src = ../..;

  build-system = [ setuptools ];
  dependencies = [ chess keyring ];
  pythonImportsCheck = [ "pawnix" ];

  meta = {
    description = "Keyboard-first chess client for terminals";
    homepage = "https://github.com/a-shygun/Pawnix";
    license = lib.licenses.mit;
    mainProgram = "pawnix";
    platforms = lib.platforms.unix;
  };
})
