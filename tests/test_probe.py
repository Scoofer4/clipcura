"""ffprobe JSON -> MediaInfo, and the PTS-based variable frame rate measurement."""
from clipsana.core import probe

PHONE_HEVC = {
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "profile": "Main", "pix_fmt": "yuv420p",
         "width": 3840, "height": 2160, "r_frame_rate": "60/1", "avg_frame_rate": "1165/20",
         "color_transfer": "bt709", "color_primaries": "bt709", "color_space": "bt709",
         "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]},
        {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000", "channels": 2},
    ],
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "40.6"},
}

HLG_10BIT = {
    "streams": [
        {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le", "width": 320, "height": 180,
         "r_frame_rate": "30/1", "avg_frame_rate": "30/1", "color_transfer": "arib-std-b67"},
        # Cover art must never be mistaken for the main video stream.
        {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
    ],
    "format": {"format_name": "mov", "duration": "2.0"},
}


def test_parse_reads_video_and_audio_streams():
    m = probe.parse_probe("phone.mp4", PHONE_HEVC, size=1000)
    assert (m.video.codec, m.video.width, m.video.height) == ("hevc", 3840, 2160)
    assert (m.video.r_fps, m.video.avg_fps) == (60.0, 58.25)
    assert m.audio.sample_rate == 48000
    assert m.duration == 40.6


def test_rotation_swaps_display_dimensions():
    m = probe.parse_probe("phone.mp4", PHONE_HEVC, size=1000)
    assert m.video.rotation == -90
    assert (m.video.display_width, m.video.display_height) == (2160, 3840)


def test_bit_depth_comes_from_pixel_format_and_attached_pictures_are_skipped():
    m = probe.parse_probe("hlg.mp4", HLG_10BIT, size=1000)
    assert m.video.codec == "hevc"
    assert m.video.bit_depth == 10
    assert m.audio is None


def test_first_frame_colors_override_container_tags():
    # Android screen recordings: container says BT.709, the H.264 frames are BT.601.
    first_frame = {"color_primaries": "bt470bg", "color_transfer": "smpte170m", "color_space": "bt470bg"}
    m = probe.parse_probe("phone.mp4", PHONE_HEVC, size=1000, first_frame=first_frame)
    assert (m.video.color_primaries, m.video.color_transfer, m.video.color_space) == (
        "bt470bg", "smpte170m", "bt470bg")


def test_unknown_frame_colors_keep_container_tags():
    first_frame = {"color_primaries": "unknown", "color_transfer": "", "color_space": "unknown"}
    m = probe.parse_probe("phone.mp4", PHONE_HEVC, size=1000, first_frame=first_frame)
    assert m.video.color_primaries == "bt709"


def test_file_without_video_stream_is_reported_as_probe_error():
    m = probe.parse_probe("a.mp4", {"streams": [], "format": {"duration": "1"}}, size=10)
    assert m.video is None
    assert "no video stream" in m.probe_error


def test_pts_irregularity_is_zero_for_constant_frame_rate():
    assert probe.pts_irregularity([i / 30 for i in range(100)]) == 0.0


def test_pts_irregularity_detects_screen_recording_gaps():
    times, t = [], 0.0
    for i in range(100):
        times.append(t)
        t += 0.5 if i % 10 == 0 else 1 / 60  # long pauses while the screen is static
    assert probe.pts_irregularity(times) > 0.05
