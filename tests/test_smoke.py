"""Základní test, že balíček jde naimportovat (CI kontrola kostry)."""
import clipsana


def test_version():
    assert clipsana.__version__
