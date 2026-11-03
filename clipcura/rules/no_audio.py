"""Clip without an audio track. Optional silent track keeps timelines with linked audio consistent."""
from clipcura.core.models import FixStep, Issue, MediaInfo, Profile
from clipcura.rules import localize

MESSAGES = {
    "en": "No audio track",
    "cs": "Chybí zvuková stopa",
}


class NoAudioRule:
    id = "no_audio"
    title = "Missing audio"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        if media.video is None or media.audio is not None:
            return None
        return Issue(self.id, "info", localize(MESSAGES), profile.rules.add_silent_audio)

    def fix(self, issue: Issue, profile: Profile) -> FixStep | None:
        if not profile.rules.add_silent_audio:
            return None
        return FixStep(order=0, extra_inputs=[
            ["-f", "lavfi", "-i", f"anullsrc=r={profile.audio_rate}:cl=stereo"]])


RULE = NoAudioRule()
