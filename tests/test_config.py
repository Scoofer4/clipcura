"""App config (token, allowed roots) and the path whitelist used by the API and MCP."""
import os
from pathlib import Path

import pytest

from clipcura.core import config, security


def test_first_load_creates_config_with_random_token():
    a = config.load_config()
    assert len(a.token) >= 32
    assert config.load_config().token == a.token  # persisted, not regenerated
    assert a.approval_mode is True and a.allowed_roots == []
    assert (a.concurrency.gpu, a.concurrency.cpu) == (1, 1)


def test_allow_root_is_persisted_resolved(tmp_path):
    config.allow_root(tmp_path / "footage" / ".." / "footage")
    assert config.load_config().allowed_roots == [str((tmp_path / "footage").resolve())]


def test_path_inside_allowed_root_is_accepted(tmp_path):
    (tmp_path / "raw").mkdir()
    assert security.ensure_allowed(tmp_path / "raw", [str(tmp_path)]) == (tmp_path / "raw").resolve()


@pytest.mark.parametrize("escape", ["raw/../../outside", "../outside"])
def test_dotdot_escape_is_rejected(tmp_path, escape):
    root = tmp_path / "root"
    (root / "raw").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    with pytest.raises(security.PathNotAllowed):
        security.ensure_allowed(root / escape, [str(root)])


def test_everything_is_rejected_until_a_root_is_allowed(tmp_path):
    with pytest.raises(security.PathNotAllowed, match="allow"):
        security.ensure_allowed(tmp_path, [])


def test_link_pointing_outside_root_is_rejected(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "sneaky"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError:
        # Symlinks need Developer Mode or admin rights; a directory junction needs neither and is the
        # more likely escape route on Windows anyway.
        try:
            import _winapi
            _winapi.CreateJunction(str(outside), str(link))
        except (ImportError, OSError):
            pytest.skip("cannot create a symlink or junction here")
    with pytest.raises(security.PathNotAllowed):
        security.ensure_allowed(link, [str(root)])


def test_similar_prefix_is_not_inside(tmp_path):
    (tmp_path / "footage-private").mkdir()
    with pytest.raises(security.PathNotAllowed):
        security.ensure_allowed(tmp_path / "footage-private", [str(tmp_path / "footage")])


def test_case_differences_do_not_matter_on_windows(tmp_path):
    (tmp_path / "Raw").mkdir()
    upper = Path(str(tmp_path).upper()) / "RAW"
    assert security.ensure_allowed(upper, [str(tmp_path)])
