from app.repositories.device_repository import InMemoryDeviceRepository
from app.services.device_service import DeviceService

repository = InMemoryDeviceRepository()


def get_device_service() -> DeviceService:
    return DeviceService(repository, repository)
