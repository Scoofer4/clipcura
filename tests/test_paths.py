"""Choosing processing paths from doctor measurements (issue #5): quality first, then measured speed."""
from clipsana.core import backends
from clipsana.core.models import Benchmarks, EncoderQuality, FfmpegInfo, Probe

WORKING = ["cuda", "qsv", "h264_nvenc", "h264_qsv", "libplacebo", "zscale"]


def info(bench: Benchmarks | None = None, working=WORKING) -> FfmpegInfo:
    names = ["cuda", "qsv", "d3d11va", "h264_nvenc", "h264_qsv", "libplacebo", "zscale"]
    return FfmpegInfo(ffmpeg="f", ffprobe="p", version="8.1", benchmarks=bench,
                      probes=[Probe(name=n, ok=n in working) for n in names])


def test_fastest_measured_decoder_and_scaler_win():
    bench = Benchmarks(decode={"cpu": 90, "cuda": 400, "d3d11va": 250},
                       scale={"cpu": 60, "scale_cuda": 210, "libplacebo": 150},
                       tonemap={"zscale": 40, "libplacebo": 120})
    p = backends.choose_paths(info(bench))
    assert (p.decode, p.scale, p.tonemap) == ("cuda", "scale_cuda", "libplacebo")


def test_cpu_wins_when_it_measures_faster():
    bench = Benchmarks(decode={"cpu": 500, "cuda": 400}, scale={"cpu": 300, "scale_cuda": 210})
    p = backends.choose_paths(info(bench))
    assert (p.decode, p.scale) == ("cpu", "cpu")


def test_higher_quality_tonemapping_wins_even_if_slower():
    # libplacebo (BT.2390 with peak detection) beats zscale+hable on quality, so speed does not decide here.
    p = backends.choose_paths(info(Benchmarks(tonemap={"zscale": 200, "libplacebo": 50})))
    assert p.tonemap == "libplacebo"


def test_failed_measurements_are_ignored():
    bench = Benchmarks(decode={"cpu": 90, "cuda": 0}, scale={"cpu": 60, "scale_cuda": 0},
                       tonemap={"zscale": 40, "libplacebo": 0})
    p = backends.choose_paths(info(bench))
    assert (p.decode, p.scale, p.tonemap) == ("cpu", "cpu", "zscale")


def test_without_measurements_uses_probes_and_safe_defaults():
    p = backends.choose_paths(info())
    assert (p.decode, p.encode, p.scale, p.tonemap) == ("cuda", "cuda", "cpu", "libplacebo")


def test_without_ffmpeg_everything_runs_on_cpu():
    p = backends.choose_paths(None)
    assert (p.decode, p.encode, p.scale, p.tonemap) == ("cpu", "cpu", "cpu", "zscale")


def test_intel_only_machine_decodes_with_d3d11va_not_qsv():
    # -hwaccel qsv leaves frames in GPU memory (filters fail); d3d11va downloads them at full bit depth.
    p = backends.choose_paths(info(working=["qsv", "h264_qsv", "d3d11va"]))
    assert (p.decode, p.encode) == ("d3d11va", "qsv")


def test_encoder_backend_follows_capability_not_decode_speed():
    p = backends.choose_paths(info(Benchmarks(decode={"cpu": 500, "cuda": 100})))
    assert (p.decode, p.encode) == ("cpu", "cuda")


def test_gpu_encoder_quality_calibration_reaches_the_paths():
    # Issue #14: doctor measured that h264_nvenc matches libx264 at CQ 15, while hevc_nvenc never matched libx265.
    quality = {"h264_nvenc": EncoderQuality(cpu_encoder="libx264", metric="vmaf", quality=15, delta=0.2),
               "hevc_nvenc": EncoderQuality(cpu_encoder="libx265", metric="vmaf", quality=None, delta=-1.4)}
    p = backends.choose_paths(info(Benchmarks(quality=quality)))
    assert p.gpu_quality == {"h264_nvenc": 15}
    assert p.cpu_only == ["hevc_nvenc"]


def test_parity_picks_the_first_quality_step_that_matches_cpu_on_every_clip():
    # deltas = GPU score minus CPU score per test clip, for each quality step in ladder order
    assert backends.first_matching([(19, [0.8, -1.2]), (17, [1.0, -0.3]), (15, [1.2, 0.1])], margin=0.5) == (17, -0.3)
    assert backends.first_matching([(19, [-2.0]), (17, [-0.9])], margin=0.5) == (None, -0.9)
