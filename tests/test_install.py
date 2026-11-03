"""How Clipcura was installed decides where its data lives (#21): a portable ZIP keeps it next to the app."""
import pytest

from clipcura.core import paths


@pytest.fixture
def app_folder(tmp_path, monkeypatch):
    folder = tmp_path / "Clipcura"
    folder.mkdir()
    monkeypatch.delenv("CLIPCURA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(paths, "install_dir", lambda: folder)
    paths.portable_data_dir.cache_clear()
    yield folder
    paths.portable_data_dir.cache_clear()


def test_portable_package_keeps_data_next_to_the_app(app_folder):
    (app_folder / paths.PORTABLE_MARKER).write_text("")
    assert paths.install_kind() == "portable"
    assert paths.app_data_dir() == app_folder / "data"
    assert (app_folder / "data").is_dir()


def test_installed_app_uses_the_user_profile(app_folder, tmp_path):
    assert paths.install_kind() == "installed"
    assert paths.app_data_dir() == tmp_path / "roaming" / "Clipcura"


def test_read_only_portable_folder_falls_back_to_the_user_profile(app_folder, tmp_path, monkeypatch):
    (app_folder / paths.PORTABLE_MARKER).write_text("")

    def refuse(*_a, **_k):
        raise PermissionError("read-only medium")

    monkeypatch.setattr(paths.Path, "mkdir", refuse)
    assert paths.app_data_dir() == tmp_path / "roaming" / "Clipcura"
    assert paths.install_kind() == "portable"   # still the portable package, only its data lives elsewhere


def test_clipcura_home_wins_over_portable_data(app_folder, tmp_path, monkeypatch):
    (app_folder / paths.PORTABLE_MARKER).write_text("")
    monkeypatch.setenv("CLIPCURA_HOME", str(tmp_path / "dev-home"))
    assert paths.app_data_dir() == tmp_path / "dev-home"


def test_portable_app_does_not_adopt_old_profile_data(app_folder, tmp_path):
    (app_folder / paths.PORTABLE_MARKER).write_text("")
    (tmp_path / "roaming" / paths.LEGACY_NAME).mkdir(parents=True)
    assert paths.migrate_legacy_app_data() is None
    assert (tmp_path / "roaming" / paths.LEGACY_NAME).is_dir()


def test_source_checkout(monkeypatch):
    monkeypatch.setattr(paths, "install_dir", lambda: None)
    assert paths.install_kind() == "source"
