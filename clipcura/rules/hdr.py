"""HDR (PQ / HLG) footage on an SDR Rec.709 timeline looks washed out or clipped."""
from clipcura.core.models import FixStep, Issue, MediaInfo, Profile
from clipcura.rules import localize

HDR_TRANSFERS = {"smpte2084": "PQ", "arib-std-b67": "HLG"}

# CPU path (zimg): linearize, tone-map in float RGB, then back to limited-range Rec.709.
ZSCALE_TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                  "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")
# GPU path (Vulkan, any vendor): same result in one filter, chosen by measurement (issue #5).
LIBPLACEBO_TONEMAP = ("libplacebo=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv:"
                      "tonemapping=auto")

MESSAGES = {
    "en": "HDR video ({kind}) - will be tone-mapped to SDR Rec.709",
    "cs": "HDR video ({kind}) - převede se do SDR Rec.709",
}


class HdrRule:
    id = "hdr"
    title = "HDR footage"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        v = media.video
        if v is None or v.color_transfer not in HDR_TRANSFERS:
            return None
        kind = HDR_TRANSFERS[v.color_transfer]
        return Issue(self.id, "warning", localize(MESSAGES, kind=kind), True,
                     {"color_transfer": v.color_transfer, "color_primaries": v.color_primaries})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        return FixStep(order=20, video_filters=[ZSCALE_TONEMAP],
                       gpu_variant={"tonemap:libplacebo": [LIBPLACEBO_TONEMAP]})


RULE = HdrRule()
