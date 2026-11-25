from datetime import datetime
from ipaddress import ip_address
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class DeviceCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "device_id": "RTR-101",
            "name": "Branch Router",
            "device_type": "router",
            "ip_address": "192.168.10.1",
            "status": "online",
        }
    })

    device_id: str
    name: str
    device_type: Literal["router", "switch", "server"]
    ip_address: str
    status: Literal["online", "offline"] = "online"

    @field_validator("ip_address")
    @classmethod
    def validate_ipv4(cls, value: str) -> str:
        address = ip_address(value)
        if address.version != 4:
            raise ValueError("ip_address must be an IPv4 address")
        return value


class DeviceResponse(BaseModel):
    device_id: str
    name: str
    device_type: Literal["router", "switch", "server"]
    ip_address: str
    status: Literal["online", "offline"]


class StatusUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"status": "offline"}})

    status: Literal["online", "offline"]


class AlertResponse(BaseModel):
    device_id: str
    message: str
    timestamp: datetime
