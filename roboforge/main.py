from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from roboforge.api import router

app = FastAPI(title="RoboForge Engine", version="0.1.0",
              description="Robotics design backend with finance, voice, telemetry, and adaptive UI integrations.")
app.include_router(router)

WEB_ROOT = Path(__file__).resolve().parent / "web"
app.mount("/ui/assets", StaticFiles(directory=WEB_ROOT), name="ui-assets")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(WEB_ROOT / "index.html", headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                   "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
                                   "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(self)",
    })


@app.get("/health")
def health():
    return {"status": "ok"}
