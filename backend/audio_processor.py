import re
import subprocess
import threading
import struct
import os
import logging
import time
import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit = 2 bytes
CHUNK_DURATION_MS = 100
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH * CHANNELS
SILENCE = b'\x00' * CHUNK_BYTES

HLS_DIR = "/tmp/hls"

RECONNECT_DELAY_MIN = 3   # seconds
RECONNECT_DELAY_MAX = 60  # seconds


def _mask_url(url: str) -> str:
    """Hide credentials before writing a URL to the logs."""
    return re.sub(r"//[^@/]*@", "//***@", url)


def _stop_process(proc):
    """Stop a child process and reap it, so that no ffmpeg is left behind.

    Closing stdin first matters: ffmpeg blocked on reading its input pipe
    ignores a single SIGTERM as long as the write end stays open.
    """
    if proc is None:
        return
    if proc.stdin:
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    if proc.stdout:
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass


class AudioProcessor:
    def __init__(self, rtsp_url: str, threshold: int = 500):
        self.rtsp_url = rtsp_url
        self.threshold = threshold
        self.current_level = 0.0
        self.is_sound_detected = False
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._ffmpeg_in = None
        self._ffmpeg_out = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Audio processor started")

    def stop(self):
        self._running = False
        self._stop_event.set()
        for proc in (self._ffmpeg_in, self._ffmpeg_out):
            if proc and proc.poll() is None:
                proc.terminate()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Audio processor stopped")

    def set_threshold(self, value: int):
        with self._lock:
            self.threshold = value
        logger.info(f"Threshold set to {value}")

    def get_status(self) -> dict:
        with self._lock:
            return {
                "level": float(round(self.current_level, 1)),
                "threshold": int(self.threshold),
                "sound_detected": bool(self.is_sound_detected),
            }

    def _run(self):
        delay = RECONNECT_DELAY_MIN
        while self._running:
            started = time.monotonic()
            try:
                self._process_stream()
            except Exception as e:
                logger.error(f"Stream error: {e}")
            if not self._running:
                break
            # A stream that lasted is a healthy one: reset the backoff
            if time.monotonic() - started > RECONNECT_DELAY_MAX:
                delay = RECONNECT_DELAY_MIN
            # Always wait before reconnecting, also when the stream ended
            # without raising (camera unreachable, ffmpeg exited)
            logger.info(f"Reconnecting in {delay} seconds...")
            self._stop_event.wait(delay)
            delay = min(delay * 2, RECONNECT_DELAY_MAX)

    def _process_stream(self):
        os.makedirs(HLS_DIR, exist_ok=True)

        # FFmpeg: RTSP → raw PCM on stdout
        self._ffmpeg_in = subprocess.Popen(
            [
                "ffmpeg",
                "-rtsp_transport", "tcp",
                "-i", self.rtsp_url,
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                "-f", "s16le",
                "-loglevel", "warning",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            # Not read anywhere: a pipe would fill up and block ffmpeg
            stderr=subprocess.DEVNULL,
        )

        # FFmpeg: raw PCM on stdin → HLS output
        hls_path = os.path.join(HLS_DIR, "stream.m3u8")
        self._ffmpeg_out = subprocess.Popen(
            [
                "ffmpeg",
                "-f", "s16le",
                "-ar", str(SAMPLE_RATE),
                "-ac", str(CHANNELS),
                "-i", "pipe:0",
                "-c:a", "aac",
                "-b:a", "64k",
                "-f", "hls",
                "-hls_time", "2",
                "-hls_list_size", "5",
                "-hls_flags", "delete_segments+append_list",
                "-loglevel", "warning",
                hls_path,
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        logger.info(f"Connecting to RTSP stream: {_mask_url(self.rtsp_url)}")
        connected = False

        try:
            while self._running:
                chunk = self._ffmpeg_in.stdout.read(CHUNK_BYTES)
                if not chunk or len(chunk) < CHUNK_BYTES:
                    if self._ffmpeg_in.poll() is not None:
                        logger.warning(
                            "FFmpeg input process exited "
                            f"(code {self._ffmpeg_in.returncode})"
                        )
                        break
                    continue

                if not connected:
                    connected = True
                    logger.info("Receiving audio from RTSP stream")

                # Calculate RMS level
                samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float64)
                rms = np.sqrt(np.mean(samples ** 2))

                with self._lock:
                    self.current_level = rms
                    threshold = self.threshold
                    self.is_sound_detected = rms > threshold

                # Gate: pass audio or silence
                if rms > threshold:
                    output = chunk
                else:
                    output = SILENCE

                try:
                    self._ffmpeg_out.stdin.write(output)
                    self._ffmpeg_out.stdin.flush()
                except BrokenPipeError:
                    logger.warning("FFmpeg output pipe broken")
                    break

        finally:
            _stop_process(self._ffmpeg_out)
            _stop_process(self._ffmpeg_in)
