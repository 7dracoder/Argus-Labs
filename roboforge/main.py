from fastapi import FastAPI

from roboforge.api import router

app = FastAPI(title="RoboForge Engine", version="0.1.0",
              description="Robotics design backend with finance, voice, telemetry, and adaptive UI integrations.")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
