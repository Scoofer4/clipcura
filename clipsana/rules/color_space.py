"""SDR footage coded in BT.601 (common in Android screen recordings) on a Rec.709 timeline.

The editor follows the tags, so a file whose pixels are BT.601 must leave as real BT.709, not just relabelled.
"""
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import localize

REC709 = {"bt709"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # handled by the hdr rule's tone-mapping

MESSAGES = {
    "en": "Colours coded as {space} - will be converted to Rec.709 during conversion",
    "cs": "Barvy jsou kódované jako {space} - při převodu se převedou do Rec.709",
}


class ColorSpaceRule:
    id = "color_space"
    title = "Non-Rec.709 colours"
    # Editors read BT.601 tags fine on their own: worth fixing only when the file is re-encoded anyway.
    standalone = False

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None or v.color_transfer in HDR_TRANSFERS:
            return None
        tagged = {t for t in (v.color_primaries, v.color_space) if t}
        if not tagged or tagged <= REC709:
            return None  # untagged footage is treated as Rec.709, like editors do
        space = v.color_space or v.color_primaries
        return Issue(self.id, "info", localize(MESSAGES, space=space), True,
                     {"color_primaries": v.color_primaries, "color_space": v.color_space,
                      "color_transfer": v.color_transfer})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        # zscale reads the source colours from frame properties and converts matrix, transfer and primaries.
        return FixStep(order=25, video_filters=["zscale=m=709:t=709:p=709:r=tv"])


RULE = ColorSpaceRule()
