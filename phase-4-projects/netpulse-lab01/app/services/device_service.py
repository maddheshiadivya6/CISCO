from app.events import create_offline_alert
from app.repositories.interfaces import AlertRepository, DeviceRepository


class DeviceAlreadyExistsError(Exception):
    pass


class DeviceNotFoundError(Exception):
    pass


class DeviceService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        alert_repository: AlertRepository,
    ):
        self._device_repository = device_repository
        self._alert_repository = alert_repository

    def register(self, device: dict) -> dict:
        device_id = device["device_id"]
        if self._device_repository.get_device(device_id) is not None:
            raise DeviceAlreadyExistsError(device_id)
        return self._device_repository.add_device(device)

    def list_alerts(self) -> list[dict]:
        return self._alert_repository.list_alerts()

    def list(self) -> list[dict]:
        return self._device_repository.list_devices()

    def get(self, device_id: str) -> dict:
        device = self._device_repository.get_device(device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device

    def update_status(self, device_id: str, status: str) -> dict:
        current = self._device_repository.get_device(device_id)
        if current is None:
            raise DeviceNotFoundError(device_id)

        previous_status = current["status"]
        updated = self._device_repository.update_status(device_id, status)
        if previous_status == "online" and status == "offline":
            create_offline_alert(self._alert_repository, device_id)
        return updated
