"""Frame rate differs from the project's target."""
from clipcura.core.models import FixStep, Issue, MediaInfo, Profile
from clipcura.rules import fmt_fps, localize

TOLERANCE = 0.01  # fps; 29.97 vs 30 must still count, Resolve treats them as different rates
MAX_SANE_FPS = 240  # screen recorders write timebase-like values (90000) into the nominal rate

MESSAGES = {
    "en": "Frame rate {src} fps differs from the project's {dst} fps",
    "cs": "Snímková frekvence {src} fps se liší od projektu ({dst} fps)",
}
JUDDER = {
    "en": " - converting will repeat frames unevenly (judder)",
    "cs": " - převod bude nerovnoměrně opakovat snímky (trhání pohybu)",
}


class FpsMismatchRule:
    id = "fps_mismatch"
    title = "Frame rate differs from profile"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None:
            return None
        # The nominal rate is what the camera aimed for (60 fps phone footage that averages 58.26 because of
        # VFR); the average is only a fallback when the nominal value is clearly not a frame rate.
        src = v.r_fps if 0 < v.r_fps <= MAX_SANE_FPS else v.avg_fps
        if not src or abs(src - profile.fps) <= TOLERANCE:
            return None
        # Dropping every other frame (60 -> 30) is clean; 24/25 -> 30 must duplicate frames unevenly.
        ratio = src / profile.fps
        clean = round(ratio) >= 1 and abs(ratio - round(ratio)) < 0.01
        message = localize(MESSAGES, src=fmt_fps(src), dst=fmt_fps(profile.fps))
        if not clean:
            message += localize(JUDDER)
        return Issue(self.id, "info" if clean else "warning", message, True,
                     {"fps": src, "target_fps": profile.fps})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        return FixStep(order=40, video_filters=[f"fps=fps={fmt_fps(profile.fps)}"],
                       output_args=["-fps_mode", "cfr"])


RULE = FpsMismatchRule()
