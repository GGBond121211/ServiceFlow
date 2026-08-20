import serviceflow


def test_package_exposes_version() -> None:
    assert serviceflow.__version__ == "0.1.0"
