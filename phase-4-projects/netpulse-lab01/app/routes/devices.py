from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_device_service
from app.models import AlertResponse, DeviceCreate, DeviceResponse, StatusUpdate
from app.services.device_service import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    DeviceService,
)

router = APIRouter()


@router.post("/devices", response_model=DeviceResponse, status_code=status.HTTP_201_CREATED,
            responses={409: {"description": "Device ID already exists"}})
def register_device(
    device: DeviceCreate,
    service: DeviceService = Depends(get_device_service),
):
    try:
        return service.register(device.model_dump())
    except DeviceAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/devices", response_model=list[DeviceResponse])
def list_devices(service: DeviceService = Depends(get_device_service)):
    return service.list()


@router.get("/devices/{device_id}", response_model=DeviceResponse,
           responses={404: {"description": "Device not found"}})
def get_device(device_id: str, service: DeviceService = Depends(get_device_service)):
    try:
        return service.get(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")


@router.patch("/devices/{device_id}/status", response_model=DeviceResponse,
             responses={404: {"description": "Device not found"}})
def update_device_status(
    device_id: str,
    update: StatusUpdate,
    service: DeviceService = Depends(get_device_service),
):
    try:
        return service.update_status(device_id, update.status)
    except DeviceNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")


@router.get("/alerts", response_model=list[AlertResponse])
def list_alerts(service: DeviceService = Depends(get_device_service)):
    return service.list_alerts()
