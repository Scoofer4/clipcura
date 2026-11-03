"""The Monogram drawn for the tray and the installer (#9): progress fills the C, a badge asks for attention."""
import io

from PIL import Image

from clipsana.desktop import icon


def pixel(img: Image.Image, x: float, y: float) -> tuple[int, int, int, int]:
    """Colour at a point given in the 64x64 logo grid of ui/public/favicon.svg."""
    s = img.width / 64
    return img.getpixel((int(x * s), int(y * s)))


def test_idle_icon_is_the_full_monogram():
    img = icon.draw(64)
    assert img.size == (64, 64) and img.mode == "RGBA"
    assert pixel(img, 2, 32)[:3] == icon.BG                 # dark tile
    left = pixel(img, 10, 32)                               # the C on the left
    assert left[0] > 180 and left[1] < 100                  # brand crimson
    assert pixel(img, 34, 32)[:3] > (200, 200, 200)         # the play triangle
    assert pixel(img, 54, 32)[:3] == icon.BG                # the C is open on the right


def test_progress_fills_the_c_from_its_top_end():
    half = icon.draw(64, progress=0.5)
    assert pixel(half, 22, 13)[0] > 180                     # near the top end: done, accent
    assert pixel(half, 22, 51)[:3] == icon.TRACK            # near the bottom end: still to go
    assert pixel(icon.draw(64, progress=0.0), 22, 13)[:3] == icon.TRACK
    assert pixel(icon.draw(64, progress=1.0), 22, 51)[0] > 180


def test_attention_badge_for_requests_waiting_for_approval():
    assert pixel(icon.draw(64, attention=True), 52, 12)[:3] == icon.ATTENTION
    assert pixel(icon.draw(64), 52, 12)[:3] != icon.ATTENTION


def test_png_for_the_tray_and_ico_for_windows(tmp_path):
    assert Image.open(io.BytesIO(icon.png(32, progress=0.3))).size == (32, 32)
    path = icon.write_ico(tmp_path / "clipsana.ico")
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= Image.open(path).info["sizes"]
