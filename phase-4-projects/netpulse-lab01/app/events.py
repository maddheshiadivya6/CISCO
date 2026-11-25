from datetime import datetime, timezone

from app.repositories.interfaces import AlertRepository


def create_offline_alert(repository: AlertRepository, device_id: str) -> dict:
    return repository.save_alert({
        "device_id": device_id,
        "message": f"Device {device_id} changed from online to offline",
        "timestamp": datetime.now(timezone.utc),
    })
