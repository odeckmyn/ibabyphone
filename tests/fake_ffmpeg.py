#!/usr/bin/env python3
"""Stand-in for the ffmpeg binary, used by the test suite.

It is copied as an executable named "ffmpeg" in a directory put first in PATH.
The role is deduced from the arguments AudioProcessor passes:

- input role ("-rtsp_transport" present), driven by FAKE_FFMPEG_INPUT:
    fail  exit with code 1 right away, like an unreachable camera
    pcm   write loud chunks, then quiet chunks, then wait to be terminated
- output role (reads "pipe:0"): copy stdin to FAKE_FFMPEG_SINK until EOF.
  Like the real ffmpeg blocked on its input pipe, it does not quit on a
  single SIGTERM: it only ends when its stdin is closed.

Every instance records its PID in FAKE_FFMPEG_PIDDIR.
"""
import os
import signal
import struct
import sys
import time

CHUNK_SAMPLES = 1600  # 100 ms at 16 kHz, as in audio_processor.py


def record_pid(role):
    piddir = os.environ.get("FAKE_FFMPEG_PIDDIR")
    if piddir:
        with open(os.path.join(piddir, f"{role}-{os.getpid()}"), "w"):
            pass


def chunk(amplitude):
    return struct.pack(f"<{CHUNK_SAMPLES}h", *([amplitude] * CHUNK_SAMPLES))


def run_input():
    record_pid("in")
    mode = os.environ.get("FAKE_FFMPEG_INPUT", "fail")
    if mode == "fail":
        sys.exit(1)
    count = int(os.environ.get("FAKE_FFMPEG_CHUNKS", "5"))
    out = sys.stdout.buffer
    for amplitude in (10000, 10):
        for _ in range(count):
            out.write(chunk(amplitude))
            out.flush()
    while True:
        time.sleep(1)


def run_output():
    record_pid("out")
    signal.signal(signal.SIGTERM, lambda signum, frame: None)
    sink_path = os.environ.get("FAKE_FFMPEG_SINK", os.devnull)
    with open(sink_path, "ab") as sink:
        while True:
            data = sys.stdin.buffer.read1(65536)
            if not data:
                break
            sink.write(data)
            sink.flush()


if __name__ == "__main__":
    if "-rtsp_transport" in sys.argv:
        run_input()
    else:
        run_output()
