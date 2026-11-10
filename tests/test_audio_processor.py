import logging
import re

import audio_processor
from audio_processor import CHUNK_BYTES, SILENCE, _mask_url
from conftest import wait_until


def test_mask_url_hides_credentials():
    url = "rtsp://admin:pa%40ss1234@192.168.1.71:554/h264Preview_01_sub"
    assert _mask_url(url) == "rtsp://***@192.168.1.71:554/h264Preview_01_sub"


def test_mask_url_without_credentials():
    url = "rtsp://192.168.1.71:554/h264Preview_01_sub"
    assert _mask_url(url) == url


def test_no_ffmpeg_left_behind_when_camera_unreachable(
    fake_ffmpeg, make_processor, monkeypatch
):
    """Regression test: an unreachable camera used to leak one ffmpeg per retry."""
    monkeypatch.setenv("FAKE_FFMPEG_INPUT", "fail")
    monkeypatch.setattr(audio_processor, "RECONNECT_DELAY_MIN", 0.05)
    monkeypatch.setattr(audio_processor, "RECONNECT_DELAY_MAX", 0.05)

    processor = make_processor()
    processor.start()
    assert wait_until(lambda: len(fake_ffmpeg.pids("in")) >= 5)

    # While it keeps retrying, at most one input and one output are alive
    assert len(fake_ffmpeg.running()) <= 2

    processor.stop()
    assert wait_until(lambda: not fake_ffmpeg.running())


def test_reconnect_delay_backs_off(fake_ffmpeg, make_processor, monkeypatch, caplog):
    monkeypatch.setenv("FAKE_FFMPEG_INPUT", "fail")
    monkeypatch.setattr(audio_processor, "RECONNECT_DELAY_MIN", 0.05)
    monkeypatch.setattr(audio_processor, "RECONNECT_DELAY_MAX", 0.2)
    caplog.set_level(logging.INFO, logger="audio_processor")

    def delays():
        return [
            float(m.group(1))
            for record in caplog.records
            if (m := re.match(r"Reconnecting in ([\d.]+) seconds", record.getMessage()))
        ]

    processor = make_processor()
    processor.start()
    assert wait_until(lambda: len(delays()) >= 5)
    processor.stop()

    assert delays()[:5] == [0.05, 0.1, 0.2, 0.2, 0.2]


def test_password_never_logged(fake_ffmpeg, make_processor, monkeypatch, caplog):
    monkeypatch.setenv("FAKE_FFMPEG_INPUT", "fail")
    monkeypatch.setattr(audio_processor, "RECONNECT_DELAY_MIN", 0.05)
    monkeypatch.setattr(audio_processor, "RECONNECT_DELAY_MAX", 0.05)
    caplog.set_level(logging.INFO, logger="audio_processor")

    processor = make_processor(rtsp_url="rtsp://admin:secret@192.0.2.1:554/sub")
    processor.start()
    assert wait_until(lambda: len(fake_ffmpeg.pids("in")) >= 2)
    processor.stop()

    assert "Connecting to RTSP stream" in caplog.text
    assert "secret" not in caplog.text


def test_gating_passes_loud_audio_and_mutes_quiet_audio(
    fake_ffmpeg, make_processor, monkeypatch
):
    chunks = 5
    monkeypatch.setenv("FAKE_FFMPEG_INPUT", "pcm")
    monkeypatch.setenv("FAKE_FFMPEG_CHUNKS", str(chunks))

    processor = make_processor(threshold=500)
    processor.start()
    expected = 2 * chunks * CHUNK_BYTES
    assert wait_until(
        lambda: fake_ffmpeg.sink.exists()
        and fake_ffmpeg.sink.stat().st_size >= expected
    )

    # The last chunks are quiet: the level is low and nothing is detected
    status = processor.get_status()
    assert status["level"] < status["threshold"]
    assert status["sound_detected"] is False

    processor.stop()
    assert wait_until(lambda: not fake_ffmpeg.running())

    data = fake_ffmpeg.sink.read_bytes()
    loud, quiet = data[: chunks * CHUNK_BYTES], data[chunks * CHUNK_BYTES : expected]
    assert loud != SILENCE * chunks
    assert quiet == SILENCE * chunks
