"""Smoke test: the package installs and imports with the expected version."""


def test_package_imports_with_version():
    import pipecat_ojin

    assert pipecat_ojin.__version__ == "0.1.4"
