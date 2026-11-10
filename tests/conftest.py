import os
import shutil
import stat
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import audio_processor  # noqa: E402


def _is_running(pid: int) -> bool:
    """True if the process exists and is not a zombie (Linux only)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            # The state is the first field after the "(comm)" one
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


class FakeFFmpeg:
    def __init__(self, piddir: Path, sink: Path):
        self.piddir = piddir
        self.sink = sink

    def pids(self, role: str = "") -> list[int]:
        return [
            int(p.name.split("-")[1])
            for p in self.piddir.iterdir()
            if p.name.startswith(role)
        ]

    def running(self) -> list[int]:
        return [pid for pid in self.pids() if _is_running(pid)]


def wait_until(condition, timeout: float = 10.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return bool(condition())


@pytest.fixture
def fake_ffmpeg(tmp_path, monkeypatch):
    """Put a fake ffmpeg first in PATH and send the HLS output to tmp_path."""
    bindir = tmp_path / "bin"
    piddir = tmp_path / "pids"
    bindir.mkdir()
    piddir.mkdir()

    exe = bindir / "ffmpeg"
    exe.write_text(
        f"#!{sys.executable}\n" + (ROOT / "tests" / "fake_ffmpeg.py").read_text()
    )
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    sink = tmp_path / "sink.pcm"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_FFMPEG_PIDDIR", str(piddir))
    monkeypatch.setenv("FAKE_FFMPEG_SINK", str(sink))
    monkeypatch.setattr(audio_processor, "HLS_DIR", str(tmp_path / "hls"))
    assert shutil.which("ffmpeg") == str(exe)

    return FakeFFmpeg(piddir, sink)


@pytest.fixture
def make_processor():
    """Build AudioProcessor instances and stop them at the end of the test."""
    created = []

    def _make(**kwargs):
        kwargs.setdefault("rtsp_url", "rtsp://admin:secret@192.0.2.1:554/sub")
        processor = audio_processor.AudioProcessor(**kwargs)
        created.append(processor)
        return processor

    yield _make
    for processor in created:
        processor.stop()
