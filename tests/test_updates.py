"""New versions and missing parts (#22): nothing goes over the network or gets installed without consent, and
every download is checked against the release's checksums."""
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from clipcura.core import updates

ASSET_ZIP = "Clipcura-0.2.0-win64-portable.zip"
ASSET_EXE = "Clipcura-Setup-0.2.0.exe"


def portable_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Clipcura/Clipcura.exe", b"new exe")
        z.writestr("Clipcura/portable.txt", b"")
    return buf.getvalue()


class FakeGitHub:
    """Release feed and downloads; counts requests so tests can prove that nothing was asked."""

    def __init__(self, version="v0.2.0", tamper=False, no_release=False):
        self.requests: list[str] = []
        self.files = {ASSET_ZIP: portable_zip(), ASSET_EXE: b"installer bytes"}
        sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in self.files.items())
        if tamper:
            self.files[ASSET_ZIP] = b"something else"
        self.files["SHA256SUMS.txt"] = sums.encode()
        self.version, self.no_release = version, no_release

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path.endswith("/releases/latest"):
            if self.no_release:
                return httpx.Response(404, json={"message": "Not Found"})
            assets = [{"name": n, "browser_download_url": f"https://dl.example/{n}", "size": len(b)}
                      for n, b in self.files.items()]
            return httpx.Response(200, json={"tag_name": self.version, "html_url": "https://github.com/r/v",
                                             "body": "What changed", "assets": assets})
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=self.files[name])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPCURA_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def make(fake: FakeGitHub, kind="installed", install_dir=None, current="0.1.0") -> updates.Updater:
    return updates.Updater(http=fake.client(), kind=kind, install_dir=install_dir, current=current)


@pytest.mark.parametrize(("candidate", "current", "newer"), [
    ("v0.2.0", "0.1.0", True), ("0.1.0", "0.1.0", False), ("0.10.0", "0.9.1", True), ("0.1.0", "0.2.0", False),
])
def test_version_comparison(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_no_automatic_check_without_consent(home):
    fake = FakeGitHub()
    up = make(fake)
    for consent in (None, False):
        up.maybe_check(consent)
    assert fake.requests == []


def test_automatic_check_at_most_once_a_day(home):
    fake = FakeGitHub()
    up = make(fake)
    up.maybe_check(True, wait=True)
    up.maybe_check(True, wait=True)
    assert len(fake.requests) == 1
    assert up.status()["latest"]["version"] == "0.2.0"
    # A day later it asks again.
    state = json.loads((home / "updates.json").read_text(encoding="utf-8"))
    state["last_check"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    (home / "updates.json").write_text(json.dumps(state), encoding="utf-8")
    up.maybe_check(True, wait=True)
    assert len(fake.requests) == 2


def test_same_version_is_not_offered(home):
    up = make(FakeGitHub(version="v0.1.0"))
    up.check()
    assert up.status()["latest"] is None


def test_no_published_release_yet(home):
    up = make(FakeGitHub(no_release=True))
    assert up.check() is None and up.status()["latest"] is None


def test_installed_copy_downloads_the_installer_and_verifies_it(home):
    up = make(FakeGitHub())
    up.check()
    path = up.download(wait=True)
    assert path.name == ASSET_EXE and path.read_bytes() == b"installer bytes"
    assert up.status()["download"]["state"] == "ready"


def test_tampered_download_is_refused_and_removed(home):
    up = make(FakeGitHub(tamper=True), kind="portable", install_dir=home.parent / "Clipcura")
    up.check()
    with pytest.raises(ValueError, match="SHA-256"):
        up.download(wait=True)
    assert up.status()["download"]["state"] == "failed"
    assert not list((home / "updates").rglob(ASSET_ZIP))


def test_source_checkout_has_no_package_to_download(home):
    up = make(FakeGitHub(), kind="source")
    up.check()
    assert up.status()["latest"]["package"] is None
    with pytest.raises(updates.UpdateError):
        up.download(wait=True)


def test_portable_update_unpacks_next_to_the_current_copy(home, tmp_path):
    current = tmp_path / "apps" / "Clipcura"
    (current / "data").mkdir(parents=True)
    (current / "data" / "config.json").write_text("{}", encoding="utf-8")
    up = make(FakeGitHub(), kind="portable", install_dir=current)
    up.check()
    up.download(wait=True)
    exe = up.unpack_portable()
    assert exe == tmp_path / "apps" / "Clipcura-0.2.0" / "Clipcura.exe" and exe.read_bytes() == b"new exe"
    assert (current / "data" / "config.json").is_file()   # the running copy is left as it is
    updates.carry_data(current / "data", exe.parent)
    assert (exe.parent / "data" / "config.json").is_file()


def test_microsoft_signature_check():
    assert updates.signed_by_microsoft("Valid\nCN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond")
    assert not updates.signed_by_microsoft("NotSigned\n")
    assert not updates.signed_by_microsoft("Valid\nCN=Someone Else, O=Someone Else")
