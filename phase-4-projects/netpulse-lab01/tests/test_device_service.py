import pytest

from app.repositories.device_repository import InMemoryDeviceRepository
from app.services.device_service import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DeviceService,
)


@pytest.fixture
def service():
    repository = InMemoryDeviceRepository()
    return DeviceService(repository, repository)


def online_device(device_id="RTR-101", status="online"):
    return {
        "device_id": device_id,
        "name": "Branch Router",
        "device_type": "router",
        "ip_address": "192.168.10.1",
        "status": status,
    }


def test_registration(service):
    created = service.register(online_device())
    assert created["device_id"] == "RTR-101"
    assert service.list() == [created]


def test_duplicate_registration(service):
    service.register(online_device())
    with pytest.raises(DeviceAlreadyExistsError):
        service.register(online_device())


def test_missing_device(service):
    with pytest.raises(DeviceNotFoundError):
        service.get("RTR-404")


def test_initial_offline_registration_creates_no_alert(service):
    service.register(online_device(status="offline"))
    assert service.list_alerts() == []


def test_online_to_offline_creates_one_alert(service):
    service.register(online_device())
    service.update_status("RTR-101", "offline")
    alerts = service.list_alerts()
    assert len(alerts) == 1
    assert alerts[0]["device_id"] == "RTR-101"


def test_repeated_offline_keeps_one_alert(service):
    service.register(online_device())
    service.update_status("RTR-101", "offline")
    service.update_status("RTR-101", "offline")
    assert len(service.list_alerts()) == 1
