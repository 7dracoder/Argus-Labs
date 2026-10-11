from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from roboforge.api import router

app = FastAPI(title="Argus Labs Engine", version="0.1.0",
              description="Robotics design backend with finance, voice, telemetry, and adaptive UI integrations.")
app.include_router(router)

WEB_ROOT = Path(__file__).resolve().parent / "web"


class Assets(StaticFiles):
    # index.html is no-store, so its scripts must revalidate too or a stale app.js runs against new markup.
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/ui/assets", Assets(directory=WEB_ROOT), name="ui-assets")


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(WEB_ROOT / "index.html", headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
                                   "img-src 'self' data:; media-src 'self' blob:; "
                                   # Live voice: ElevenLabs Agents WebSocket (signed URL from the backend).
                                   "connect-src 'self' wss://api.elevenlabs.io https://api.elevenlabs.io; "
                                   "object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(self)",
    })


@app.get("/health")
def health():
    return {"status": "ok"}
