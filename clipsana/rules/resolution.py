"""Resolution above the profile limit, or odd dimensions most codecs reject."""
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import localize

MESSAGES = {
    "en": "Resolution {w}x{h} - will be scaled to {tw}x{th}",
    "cs": "Rozlišení {w}x{h} - zmenší se na {tw}x{th}",
}


def _even_floor(value: float) -> int:
    return max(2, int(value) // 2 * 2)


class ResolutionRule:
    id = "resolution"
    title = "Resolution too large or odd"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None or not v.width or not v.height:
            return None
        # Display size: rotation is applied before scaling, and orientation is kept as shot (9:16 stays 9:16).
        w, h = v.display_width, v.display_height
        factor = min(1.0, profile.max_long_side / max(w, h))
        tw, th = _even_floor(w * factor), _even_floor(h * factor)
        if (tw, th) == (w, h):
            return None
        severity = "warning" if factor < 1 else "error"  # odd sizes make encoders fail outright
        return Issue(self.id, severity, localize(MESSAGES, w=w, h=h, tw=tw, th=th), True,
                     {"width": w, "height": h, "target_width": tw, "target_height": th})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        d = issue.data
        return FixStep(order=30, video_filters=[f"scale={d['target_width']}:{d['target_height']}:flags=lanczos"])


RULE = ResolutionRule()
