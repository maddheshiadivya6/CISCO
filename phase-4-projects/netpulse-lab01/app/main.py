from fastapi import FastAPI

from app.routes.devices import router

app = FastAPI(
    title="NetPulse Network Monitoring API",
    description="Modular device-monitoring API with in-memory storage.",
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
