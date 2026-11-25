from copy import deepcopy
class InMemoryDeviceRepository:
    def __init__(self):
        self._devices = {}
        self._alerts = []

    def add_device(self, device: dict) -> dict:
        stored = deepcopy(device)
        self._devices[device["device_id"]] = stored
        return deepcopy(stored)

    def list_devices(self) -> list[dict]:
        return deepcopy(list(self._devices.values()))

    def get_device(self, device_id: str):
        device = self._devices.get(device_id)
        return deepcopy(device) if device is not None else None

    def update_status(self, device_id: str, status: str) -> dict:
        self._devices[device_id]["status"] = status
        return deepcopy(self._devices[device_id])

    def save_alert(self, alert: dict) -> dict:
        stored = deepcopy(alert)
        self._alerts.append(stored)
        return deepcopy(stored)

    def list_alerts(self) -> list[dict]:
        return deepcopy(self._alerts)
