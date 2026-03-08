import asyncio
import json
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from audio_processor import AudioProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RTSP_URL = os.environ.get("RTSP_URL", "")
THRESHOLD = int(os.environ.get("THRESHOLD", "500"))
HLS_DIR = "/tmp/hls"

app = FastAPI(title="iBabyPhone")
processor = AudioProcessor(rtsp_url=RTSP_URL, threshold=THRESHOLD)


@app.on_event("startup")
async def startup():
    if not RTSP_URL:
        logger.error("RTSP_URL not set! Set it in .env file.")
        return
    processor.start()


@app.on_event("shutdown")
async def shutdown():
    processor.stop()


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/static/{filename}")
async def static_file(filename: str):
    filepath = Path(__file__).parent / "static" / filename
    if not filepath.is_file():
        return Response(status_code=404)
    return FileResponse(filepath)


@app.get("/stream/{filename}")
async def hls_stream(filename: str):
    filepath = os.path.join(HLS_DIR, filename)
    if not os.path.isfile(filepath):
        return Response(status_code=404)

    if filename.endswith(".m3u8"):
        content_type = "application/vnd.apple.mpegurl"
    elif filename.endswith(".ts"):
        content_type = "video/mp2t"
    else:
        content_type = "application/octet-stream"

    return FileResponse(
        filepath,
        media_type=content_type,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/status")
async def status():
    return processor.get_status()


@app.post("/api/threshold")
async def set_threshold(body: dict):
    value = int(body.get("threshold", THRESHOLD))
    value = max(50, min(5000, value))
    processor.set_threshold(value)
    return {"threshold": value}


@app.websocket("/ws/levels")
async def ws_levels(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = processor.get_status()
            await ws.send_text(json.dumps(data))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8585)
