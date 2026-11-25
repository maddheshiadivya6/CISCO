from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MenuInput(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    vegetarian: bool
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    capacity: int = Field(ge=0)
    active: bool = True


class MenuResponse(MenuInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class OrderLineInput(BaseModel):
    item_id: int = Field(gt=0)
    quantity: int = Field(ge=1, le=10)


class OrderInput(BaseModel):
    lines: list[OrderLineInput] = Field(min_length=1, max_length=20)


class OrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_id: int
    quantity: int
    unit_price: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    status: str
    total: Decimal
    lines: list[OrderLineResponse]


class StatusInput(BaseModel):
    status: Literal["PREPARING", "DELIVERED"]


class SessionInput(BaseModel):
    title: str = Field(default="New chat", min_length=1, max_length=120)


class MessageInput(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConfirmInput(BaseModel):
    confirm: bool
