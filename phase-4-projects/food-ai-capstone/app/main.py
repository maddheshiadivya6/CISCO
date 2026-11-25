import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router as api_router
from app.chat_api import router as chat_router
from app.database import Base, SessionLocal, engine
from app.errors import DomainError
from app.seed import seed

logger = logging.getLogger(__name__)
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
_requests = defaultdict(deque)
_rate_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="Food AI Restaurant Assistant", lifespan=lifespan)
app.include_router(api_router)
app.include_router(chat_router)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.middleware("http")
async def request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    if request.url.path.startswith("/api/"):
        address = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _rate_lock:
            timestamps = _requests[address]
            while timestamps and timestamps[0] <= now - 60:
                timestamps.popleft()
            limited = len(timestamps) >= 120
            if not limited:
                timestamps.append(now)
            if len(_requests) > 10000:
                for key in list(_requests):
                    if not _requests[key] or _requests[key][-1] <= now - 60:
                        del _requests[key]
        if limited:
            return JSONResponse(status_code=429, headers={"Retry-After": "60", "X-Request-ID": request.state.request_id},
                                content={"code": "RATE_LIMITED", "message": "Too many requests",
                                         "request_id": request.state.request_id})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, headers=exc.headers,
                        content={"code": f"HTTP_{exc.status_code}", "message": str(exc.detail),
                                 "request_id": request.state.request_id})


@app.exception_handler(DomainError)
async def domain_error(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code,
                        content={"code": f"HTTP_{exc.status_code}", "message": exc.message,
                                 "request_id": request.state.request_id})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"code": "VALIDATION_ERROR", "message": "Invalid request",
                                                 "request_id": request.state.request_id,
                                                 "details": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.exception("Unexpected request error, request_id=%s", request.state.request_id)
    return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred",
                                                 "request_id": request.state.request_id})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND / "index.html")
