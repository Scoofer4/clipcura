"""10-bit HEVC: heavy to decode and unsupported in some editor editions."""
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import localize

MESSAGES = {
    "en": "HEVC {bits}-bit - the editor may not decode it; will be converted to an editing codec",
    "cs": "HEVC {bits}-bit - střihový program ho nemusí dekódovat; převede se do střihového kodeku",
}


class Hevc10BitRule:
    id = "hevc_10bit"
    title = "10-bit HEVC"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None or v.codec != "hevc" or v.bit_depth < 10:
            return None
        return Issue(self.id, "error", localize(MESSAGES, bits=v.bit_depth), True,
                     {"codec": v.codec, "pix_fmt": v.pix_fmt, "bit_depth": v.bit_depth})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        return FixStep(order=0)  # re-encoding into the profile's codec is the fix itself


RULE = Hevc10BitRule()
