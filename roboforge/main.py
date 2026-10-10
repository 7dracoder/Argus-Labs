from fastapi import FastAPI

from roboforge.api import router

app = FastAPI(title="RoboForge Engine", version="0.1.0",
              description="Backend skeleton: projects, catalog and Finance Engine.")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
