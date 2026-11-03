"""Resolution above the profile limit, or odd dimensions most codecs reject."""
from clipcura.core.models import FixStep, Issue, MediaInfo, Profile
from clipcura.rules import localize

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
                     {"width": w, "height": h, "target_width": tw, "target_height": th, "pix_fmt": v.pix_fmt})

    def fix(self, issue: Issue, profile: Profile) -> FixStep:
        d = issue.data
        tw, th = d["target_width"], d["target_height"]
        # Same lanczos kernel on every path, so the planner may pick purely by measured speed (issue #5).
        variants = {"scale:libplacebo": [f"libplacebo=w={tw}:h={th}:downscaler=lanczos:upscaler=lanczos"]}
        upload_fmt = _CUDA_UPLOAD_FORMAT.get(d.get("pix_fmt", ""))
        if upload_fmt:
            chain = (f"format={upload_fmt},hwupload_cuda,scale_cuda={tw}:{th}:interp_algo=lanczos,"
                     f"hwdownload,format={upload_fmt}")
            variants["scale:scale_cuda"] = [chain]
        return FixStep(order=30, video_filters=[f"scale={tw}:{th}:flags=lanczos"], gpu_variant=variants)


# Only 4:2:0 sources go through scale_cuda: uploading 4:2:2/4:4:4 would mean subsampling chroma first.
_CUDA_UPLOAD_FORMAT = {"yuv420p": "yuv420p", "yuvj420p": "yuv420p", "nv12": "yuv420p",
                       "yuv420p10le": "p010le", "p010le": "p010le"}


RULE = ResolutionRule()
