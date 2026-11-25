# NetPulse

Layered FastAPI device-monitoring API with in-memory storage.

The service depends on separate device and alert repository protocols, so storage
implementations can be replaced without changing business logic or routes. The
in-memory repository currently implements both interfaces.

Start the application:

```bash
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Swagger UI: http://127.0.0.1:8000/docs

Run tests:

```bash
.venv/bin/python -m pytest -q
```
