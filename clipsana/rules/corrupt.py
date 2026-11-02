"""Unreadable or damaged files. Reported only: re-encoding broken input would hide the damage."""
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import localize

MESSAGES = {
    "en": "File is damaged or unreadable: {error}",
    "cs": "Soubor je poškozený nebo nečitelný: {error}",
}


class CorruptRule:
    id = "corrupt"
    title = "Damaged file"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        error = media.probe_error or media.decode_error
        if not error:
            return None
        return Issue(self.id, "error", localize(MESSAGES, error=error.splitlines()[-1][:160]), False,
                     {"probe_error": media.probe_error, "decode_error": media.decode_error})

    def fix(self, issue: Issue, profile: Profile) -> FixStep | None:
        return None


RULE = CorruptRule()
