"""Variable frame rate: the main reason editors crash or drift audio on phone and screen footage."""
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import fmt_fps, localize

TOLERANCE = 0.01          # relative difference between nominal and average rate
DEEP_THRESHOLD = 0.02     # share of irregular frame intervals in the deep PTS check

MESSAGES = {
    "en": "Variable frame rate ({r} vs {avg} fps on average) - the editor may crash or drift audio",
    "cs": "Proměnná snímková frekvence ({r} vs průměr {avg} fps) - střih může spadnout nebo ujet zvuk",
}


class VfrRule:
    id = "vfr"
    title = "Variable frame rate"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None:
            return None
        nominal_off = v.r_fps > 0 and v.avg_fps > 0 and abs(v.r_fps - v.avg_fps) / v.r_fps > TOLERANCE
        deep_off = media.pts_irregularity is not None and media.pts_irregularity > DEEP_THRESHOLD
        if not (nominal_off or deep_off):
            return None
        return Issue(self.id, "error", localize(MESSAGES, r=fmt_fps(v.r_fps), avg=fmt_fps(v.avg_fps)), True,
                     {"r_fps": v.r_fps, "avg_fps": v.avg_fps, "pts_irregularity": media.pts_irregularity})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        # Resampling audio against the new timeline keeps it in sync once video frames are evened out.
        return FixStep(order=40, video_filters=[f"fps=fps={fmt_fps(profile.fps)}"],
                       audio_filters=["aresample=async=1:first_pts=0"], output_args=["-fps_mode", "cfr"])


RULE = VfrRule()
