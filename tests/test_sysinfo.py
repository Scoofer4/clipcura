"""Hardware detection: GPU listings, memory, CPU and disk."""
import json
import sys

import pytest

from clipsana.core import sysinfo


def test_parse_nvidia_smi_reads_csv_rows():
    out = "NVIDIA GeForce GTX 1650 with Max-Q Design, 621.01, 4096, 312, 7\n"
    (gpu,) = sysinfo.parse_nvidia_smi(out)
    assert gpu.name == "NVIDIA GeForce GTX 1650 with Max-Q Design"
    assert gpu.vendor == "nvidia"
    assert gpu.driver == "621.01"
    assert (gpu.memory_total_mb, gpu.memory_used_mb, gpu.utilization_pct) == (4096, 312, 7)


def test_parse_video_controllers_drops_virtual_adapters_and_tags_vendor():
    raw = json.dumps([
        {"Name": "Virtual Desktop Monitor", "DriverVersion": "13.50.53.699"},
        {"Name": "Intel(R) UHD Graphics 630", "DriverVersion": "26.20.100.7927"},
        {"Name": "NVIDIA GeForce GTX 1650 with Max-Q Design", "DriverVersion": "32.0.16.2101"},
    ])
    gpus = sysinfo.parse_video_controllers(raw)
    assert [(g.vendor, g.name) for g in gpus] == [
        ("intel", "Intel(R) UHD Graphics 630"),
        ("nvidia", "NVIDIA GeForce GTX 1650 with Max-Q Design"),
    ]


def test_parse_video_controllers_accepts_single_object():
    # ConvertTo-Json emits a bare object, not a list, when there is exactly one adapter.
    raw = json.dumps({"Name": "AMD Radeon RX 6600", "DriverVersion": "31.0"})
    assert [g.vendor for g in sysinfo.parse_video_controllers(raw)] == ["amd"]


def test_merge_gpus_prefers_nvidia_smi_details():
    cim = sysinfo.parse_video_controllers(json.dumps([
        {"Name": "Intel(R) UHD Graphics 630", "DriverVersion": "26.20"},
        {"Name": "NVIDIA GeForce GTX 1650 with Max-Q Design", "DriverVersion": "32.0.16.2101"},
    ]))
    smi = sysinfo.parse_nvidia_smi("NVIDIA GeForce GTX 1650 with Max-Q Design, 621.01, 4096, 0, 0\n")
    merged = sysinfo.merge_gpus(cim, smi)
    assert [(g.vendor, g.driver) for g in merged] == [("intel", "26.20"), ("nvidia", "621.01")]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows APIs")
def test_memory_and_disk_report_positive_values(tmp_path):
    total, available = sysinfo.memory_mb()
    assert total > available > 0
    disk = sysinfo.disk_usage(tmp_path)
    assert disk.total_gb > disk.free_gb > 0
