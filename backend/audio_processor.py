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


class AudioProcessor:
    def __init__(self, rtsp_url: str, threshold: int = 500):
        self.rtsp_url = rtsp_url
        self.threshold = threshold
        self.current_level = 0.0
        self.is_sound_detected = False
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._ffmpeg_in = None
        self._ffmpeg_out = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Audio processor started")

    def stop(self):
        self._running = False
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
        while self._running:
            try:
                self._process_stream()
            except Exception as e:
                logger.error(f"Stream error: {e}")
                if self._running:
                    logger.info("Reconnecting in 3 seconds...")
                    time.sleep(3)

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
            stderr=subprocess.PIPE,
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
            stderr=subprocess.PIPE,
        )

        logger.info(f"Connected to RTSP stream: {self.rtsp_url}")

        try:
            while self._running:
                chunk = self._ffmpeg_in.stdout.read(CHUNK_BYTES)
                if not chunk or len(chunk) < CHUNK_BYTES:
                    if self._ffmpeg_in.poll() is not None:
                        logger.warning("FFmpeg input process exited")
                        break
                    continue

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
            for proc in (self._ffmpeg_in, self._ffmpeg_out):
                if proc and proc.poll() is None:
                    proc.terminate()
