"""Rotation stored only as metadata: some editors ignore it and show the clip sideways."""
from clipcura.core.models import FixStep, Issue, MediaInfo, Profile
from clipcura.rules import localize

MESSAGES = {
    "en": "Rotation {deg} degrees stored as metadata - frames will be physically rotated",
    "cs": "Otočení o {deg} stupňů je jen v metadatech - snímky se fyzicky otočí",
}


class RotationRule:
    id = "rotation"
    title = "Rotation metadata"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None or v.rotation % 360 == 0:
            return None
        return Issue(self.id, "warning", localize(MESSAGES, deg=v.rotation), True, {"rotation": v.rotation})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        # ffmpeg's default autorotate inserts the transpose at the head of the filter graph and drops the
        # display matrix from the output, so re-encoding is all it takes; an explicit filter would rotate twice.
        return FixStep(order=10)


RULE = RotationRule()
