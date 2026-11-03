"""Insta360 originals (.insv/.insp) need reframing in Insta360 Studio before editing."""
from pathlib import PurePath

from clipcura.core.models import FixStep, Issue, MediaInfo, Profile
from clipcura.rules import localize

EXTENSIONS = {".insv", ".insp"}

MESSAGES = {
    "en": "Insta360 original - export it in Insta360 Studio first",
    "cs": "Originál Insta360 - nejdřív ho exportuj v Insta360 Studio",
}


class InsvRule:
    id = "insv"
    title = "Insta360 original"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        if PurePath(media.path).suffix.lower() not in EXTENSIONS:
            return None
        return Issue(self.id, "warning", localize(MESSAGES), False)

    def fix(self, issue: Issue, profile: Profile) -> FixStep | None:
        return None


RULE = InsvRule()
