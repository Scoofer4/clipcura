"""Audio sample rate other than the project's (video standard is 48 kHz)."""
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import localize

MESSAGES = {
    "en": "Audio at {rate} Hz - will be resampled to {target} Hz",
    "cs": "Zvuk {rate} Hz - převzorkuje se na {target} Hz",
}


class AudioRateRule:
    id = "audio_rate"
    title = "Audio sample rate"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        a = media.audio
        if a is None or not a.sample_rate or a.sample_rate == profile.audio_rate:
            return None
        return Issue(self.id, "warning", localize(MESSAGES, rate=a.sample_rate, target=profile.audio_rate), True,
                     {"sample_rate": a.sample_rate, "target": profile.audio_rate})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        return FixStep(order=0, audio_filters=[f"aresample=osr={profile.audio_rate}"])


RULE = AudioRateRule()
