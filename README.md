<p align="center">
  <img src="backend/static/icon.svg" width="128" height="128" alt="iBabyPhone">
</p>

<h1 align="center">iBabyPhone</h1>

<p align="center">
  A self-hosted baby monitor that turns any Reolink IP camera into a smart audio monitor.<br>
  Runs on Docker, listens from your iPhone.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/docker-ready-blue?logo=docker" alt="Docker">
  <img src="https://img.shields.io/badge/platform-Synology%20%7C%20Linux-green" alt="Platform">
  <img src="https://img.shields.io/badge/client-Safari%20%2F%20iOS-orange?logo=safari" alt="Safari">
</p>

---

<p align="center">
  <img src="docs/screenshot.png" width="300" alt="iBabyPhone screenshot">
</p>

---

## How it works

```
Reolink camera ──RTSP──▶ FFmpeg ──▶ Python (RMS analysis) ──▶ FFmpeg ──▶ HLS stream
                                          │                                  │
                                     below threshold?                   Safari / iPhone
                                      ├─ yes → silence                 (background audio)
                                      └─ no  → pass audio through
```

The backend continuously captures audio from a Reolink camera via RTSP, computes the RMS level of each 100ms chunk, and gates the output: **real audio when the baby makes noise, silence otherwise**. The output is served as an HLS stream that Safari (iOS) can play natively in the background — just like a podcast.

## Features

- **Threshold-based audio gating** — only hear the room when it matters
- **Real-time level meter** — WebSocket-powered, updates 10x/sec
- **Background audio on iOS** — lock your phone, the sound keeps playing
- **Dark mobile-first UI** — designed for nighttime use
- **Add to Home Screen** — works as a standalone web app on iPhone
- **Auto-reconnect** — survives network hiccups gracefully
- **Adjustable sensitivity** — tweak the threshold live from the UI
- **Zero dependencies on the client** — vanilla HTML/CSS/JS, no framework

## Requirements

- A **Reolink camera** with RTSP support (tested with Reolink E1 Zoom)
- **Docker** on a NAS or any Linux machine (Synology, TrueNAS, Unraid, Raspberry Pi...)
- An **iPhone** (or any device with a modern browser)

## Quick start

### 1. Clone

```bash
git clone https://github.com/odeckmyn/ibabyphone.git
cd ibabyphone
```

### 2. Configure

```bash
cp .env.example .env
```

Edit `.env` with your camera credentials:

```env
RTSP_URL=rtsp://admin:password@192.168.1.XX:554/h264Preview_01_sub
THRESHOLD=500
```

> **Note:** if your password contains `@`, encode it as `%40` in the URL.

### 3. Run

```bash
docker compose up -d --build
```

### 4. Open

Navigate to `http://<your-server-ip>:8585` on your phone, tap **Play**.

## Add to iPhone Home Screen

1. Open the URL in **Safari**
2. Tap the **Share** icon (square with arrow)
3. Tap **Add to Home Screen**
4. Name it, tap **Add**

The app opens in full-screen mode without Safari's UI.

## Remote access (away from home)

Install [Tailscale](https://tailscale.com) on both your server and your iPhone. The baby monitor becomes accessible from anywhere via your Tailscale network — no port forwarding, no dynamic DNS.

## Architecture

```
ibabyphone/
├── backend/
│   ├── Dockerfile            # Python 3.11 + FFmpeg
│   ├── requirements.txt      # FastAPI, uvicorn, numpy
│   ├── main.py               # Web server (API + HLS + WebSocket)
│   ├── audio_processor.py    # RTSP capture, RMS analysis, gating
│   └── static/
│       └── index.html        # Mobile-first dark UI
├── docker-compose.yml
└── .env.example
```

| Component | Technology |
|-----------|-----------|
| RTSP capture | FFmpeg |
| Audio analysis | numpy (RMS) |
| Audio output | FFmpeg → HLS (AAC) |
| Web server | FastAPI + uvicorn |
| Real-time levels | WebSocket |
| Client | Vanilla HTML/JS, native HLS |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/stream/stream.m3u8` | GET | HLS audio stream |
| `/api/status` | GET | Current level + threshold |
| `/api/threshold` | POST | Update threshold `{"threshold": 500}` |
| `/ws/levels` | WS | Real-time audio levels (~10 fps) |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RTSP_URL` | — | RTSP URL of your camera (required) |
| `THRESHOLD` | `500` | Audio level threshold (50–5000) |

### Finding your RTSP URL

Most Reolink cameras use this format:

```
rtsp://admin:<password>@<camera-ip>:554/h264Preview_01_sub
```

- `_sub` = sub stream (lower bandwidth, sufficient for audio)
- `_main` = main stream (higher quality, unnecessary for audio-only)

## License

MIT — Olivier Deckmyn
