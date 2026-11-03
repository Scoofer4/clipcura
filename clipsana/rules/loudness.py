"""Programme loudness and true peak (EBU R128 measurement). Report only by default: normalising changes how the
material sounds, so the fix runs only when a profile turns it on. Measuring decodes the whole audio track,
so it also runs only when the profile asks for it.

Profile settings (under `rules.loudness`):
    measure: true          # off by default, scans stay fast
    target_lufs: -14       # -14 for social platforms, -23 for EBU R128 broadcast
    true_peak: -1          # dBTP ceiling
    tolerance_lu: 2        # report only when integrated loudness is further than this from the target
    fix: false             # true = normalise during the conversion (two-pass loudnorm, linear)
"""
import json
import math
import re
import subprocess

from clipsana.core import backends
from clipsana.core.models import FixStep, Issue, MediaInfo, Profile
from clipsana.rules import localize

MEASURE_TIMEOUT_S = 900   # whole-track decode; audio decodes at 50-100x real time
_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}")

MESSAGES = {
    "en": "Loudness {i} LUFS, true peak {tp} dBTP (target {target} LUFS, max {ceiling} dBTP) - {action}",
    "cs": "Hlasitost {i} LUFS, true peak {tp} dBTP (cíl {target} LUFS, max {ceiling} dBTP) - {action}",
}
ACTIONS = {
    "report": {"en": "normalise it in the editor, or turn on the loudness fix in the profile",
               "cs": "uprav ji ve střihu, nebo zapni opravu hlasitosti v profilu"},
    "fix": {"en": "it will be normalised during the conversion",
            "cs": "při převodu se znormalizuje"},
}
INVALID = {
    "en": "Invalid loudness setting {key}={value} (expected {expected}) - fix the profile",
    "cs": "Neplatné nastavení hlasitosti {key}={value} (očekáváno {expected}) - oprav profil",
}
_LIMITS = {"target_lufs": (-40.0, -5.0, -14.0), "true_peak": (-9.0, 0.0, -1.0), "tolerance_lu": (0.5, 10.0, 2.0)}


def _settings(profile: Profile) -> tuple[dict, Issue | None]:
    raw = profile.rules.settings(LoudnessRule.id)
    values = {}
    for key, (low, high, default) in _LIMITS.items():
        value = raw.get(key, default)
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        if not low <= number <= high:
            msg = localize(INVALID, key=key, value=value, expected=f"{low:g} to {high:g}")
            return {}, Issue(LoudnessRule.id, "warning", msg, False, {"setting": key, "value": str(value)})
        values[key] = number
    values["fix"] = bool(raw.get("fix", False))
    return values, None


def measure(path: str, target: float, ceiling: float) -> dict | None:
    """First loudnorm pass: integrated loudness, true peak, range and the values the second pass needs."""
    ffmpeg, _ = backends.find_ffmpeg()
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-i", path, "-map", "0:a:0", "-vn",
           "-af", f"loudnorm=I={target:g}:TP={ceiling:g}:print_format=json", "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=MEASURE_TIMEOUT_S, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return None
    found = _JSON.findall(p.stderr)
    if p.returncode != 0 or not found:
        return None  # unreadable audio is the corrupt rule's business
    data = json.loads(found[-1])
    return {k: float(data[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}


class LoudnessRule:
    id = "loudness"
    title = "Loudness"

    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None:
        raw = profile.rules.settings(self.id)
        if not raw.get("measure") or media.audio is None or media.probe_error:
            return None
        s, invalid = _settings(profile)
        if invalid:
            return invalid
        m = measure(media.path, s["target_lufs"], s["true_peak"])
        if m is None or not math.isfinite(m["input_i"]):
            return None  # silence has no loudness to correct
        off_target = abs(m["input_i"] - s["target_lufs"]) > s["tolerance_lu"]
        too_hot = m["input_tp"] > s["true_peak"]
        if not (off_target or too_hot):
            return None
        action = localize(ACTIONS["fix" if s["fix"] else "report"])
        msg = localize(MESSAGES, i=f"{m['input_i']:.1f}", tp=f"{m['input_tp']:.1f}", target=f"{s['target_lufs']:g}",
                       ceiling=f"{s['true_peak']:g}", action=action)
        return Issue(self.id, "info", msg, s["fix"],
                     m | {"target_lufs": s["target_lufs"], "true_peak": s["true_peak"]})

    def fix(self, issue: Issue, profile: Profile) -> FixStep | None:
        d = issue.data
        # Linear mode keeps the dynamics as recorded; it needs a range target at least as wide as the input's.
        lra = min(50, max(11, math.ceil(d["input_lra"]) + 1))
        loudnorm = (f"loudnorm=I={d['target_lufs']:g}:TP={d['true_peak']:g}:LRA={lra}"
                    f":measured_I={d['input_i']}:measured_TP={d['input_tp']}:measured_LRA={d['input_lra']}"
                    f":measured_thresh={d['input_thresh']}:offset={d['target_offset']}:linear=true:print_format=none")
        # loudnorm outputs 192 kHz, so the project rate is set again on the way out.
        return FixStep(order=90, audio_filters=[loudnorm], output_args=["-ar", str(profile.audio_rate)])


RULE = LoudnessRule()
