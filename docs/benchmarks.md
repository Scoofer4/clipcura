# Benchmarks

## HEVC 10-bit: CPU only vs GPU (acceptance criterion, CLAUDE.md §13)

Clipsana works on the CPU alone; with a GPU, the same job on HEVC 10-bit footage is measurably faster.

**Clip:** 10 s, 3840×2160, 29.97 fps, HEVC Main10 HLG (BT.2020), AAC 44.1 kHz. This is what a phone records,
and it trips up the editor in four ways at once: `hdr`, `hevc_10bit`, `fps_mismatch`, `audio_rate`.
**Job:** a full conversion as Clipsana plans it (decode → tone-map to Rec.709 → 30 fps CFR → encode, audio
resampled to 48 kHz), wall time of `service.apply`, median of 3 rounds.
**Machine:** Intel Core i7-9750H (6 cores / 12 threads), NVIDIA GeForce GTX 1650 with Max-Q Design, Windows 11,
FFmpeg 8.1 (BtbN GPL build).

| Profile | Output | CPU only | Measured path | Speed-up |
|---|---|---|---|---|
| `social-30` | DNxHR HQ 3840×2160, yuv422p, Rec.709, 30 fps | 17.5 s | 9.6 s | **1.82×** |
| `ipad-light` | H.264 1920×1080, yuv420p, Rec.709, 30 fps | 20.6 s | 10.7 s | **1.93×** |

- CPU only: decode `cpu`, scale `cpu`, tone-map `zscale`, encoder `libx264` / `dnxhd`.
- Measured path (what `clipsana doctor` picked on this machine): decode `cuda`, tone-map `libplacebo`,
  scale `cpu`, encoder `h264_nvenc` / `dnxhd`.
- DNxHR has no GPU encoder; there the GPU speeds up decoding and tone-mapping only.
- Tone-mapping takes the higher-quality path (libplacebo) whenever it works, regardless of speed (§4).
- `ipad-light` with NVENC writes H.264 High profile, like libx264 (issue #14; re-measured after the change:
  10.7 s, 1.92×).

## GPU encoders: quality against the CPU encoder (issue #14)

A faster encoder may only be used when the output quality does not drop (CLAUDE.md §4). `clipsana doctor`
encodes two lossless 1080p references (clean motion graphics, and the same with heavy grain) with each working
GPU encoder and its CPU equivalent at the profile settings, and compares both with the reference (VMAF, or
SSIM without libvmaf). It tries the GPU encoder's quality steps (CQ / `global_quality`) until the worst clip
stays within 0.5 VMAF of the CPU encoder. A GPU encoder that never matches is not used for `auto_*` codecs.

Same machine, FFmpeg 8.1:

| GPU encoder | Compared with | Setting | Worst delta (VMAF) |
|---|---|---|---|
| `h264_nvenc` | `libx264 -crf 18` | CQ 19 | −0.28 |
| `hevc_nvenc` | `libx265 -crf 20` | CQ 21 | +0.31 |
| `h264_qsv` | `libx264 -crf 18` | global_quality 21 | −0.27 |
| `hevc_qsv` | `libx265 -crf 20` | global_quality 21 | −0.47 |

- Before the fix, NVENC fell 1.1–1.2 VMAF behind on the grainy clip at any CQ: without `-maxrate` its
  constant-quality mode caps the bit rate (about 23 Mbit/s for 1080p). It now runs with `-maxrate 200M`.
- With that ceiling NVENC signals a higher level than libx264 at 1080p (H.264 5.0 instead of 4.0, HEVC 5.2).
  The editor and current iPads decode both.
- The calibration adds about 45 s to `clipsana doctor` on this machine.

Reproduce:

```powershell
uv run python tools/benchmark_hevc10.py D:\Temp\clipsana-bench --profile social-30 --rounds 3
```

The tool writes the clip, the outputs and its own app data into the given (new) folder.
