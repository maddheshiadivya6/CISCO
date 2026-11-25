from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MenuItem, Order, User
from app.repositories import MenuRepository, OrderRepository
from app.schemas import MenuInput, MenuResponse, OrderInput, OrderResponse, StatusInput
from app.security import admin_user, current_user
from app.services import begin_write, order_service

router = APIRouter(prefix="/api")


@router.get("/menu_items", response_model=list[MenuResponse])
def menu_items(category: str | None = None, vegetarian: bool | None = None,
               max_price: Decimal | None = Query(default=None, gt=0),
               keyword: str | None = None, db: Session = Depends(get_db)):
    return MenuRepository(db).search(category, vegetarian, max_price, keyword)


@router.get("/menu_items/{item_id}", response_model=MenuResponse)
def menu_item(item_id: int, db: Session = Depends(get_db)):
    item = MenuRepository(db).get(item_id)
    if not item or not item.active:
        raise HTTPException(404, "Menu item not found")
    return item


@router.post("/menu_items", response_model=MenuResponse, status_code=201)
def create_menu_item(data: MenuInput, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    begin_write(db)
    if db.scalar(select(MenuItem.id).where(MenuItem.title == data.title)) is not None:
        raise HTTPException(409, "Menu item title already exists")
    item = MenuItem(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/menu_items/{item_id}", response_model=MenuResponse)
def update_menu_item(item_id: int, data: MenuInput, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    begin_write(db)
    item = db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(404, "Menu item not found")
    duplicate = db.scalar(select(MenuItem.id).where(MenuItem.title == data.title, MenuItem.id != item_id))
    if duplicate is not None:
        raise HTTPException(409, "Menu item title already exists")
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    db.commit()
    return item


@router.delete("/menu_items/{item_id}", status_code=204)
def disable_menu_item(item_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    begin_write(db)
    item = db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(404, "Menu item not found")
    item.active = False
    db.commit()
    return Response(status_code=204)


@router.post("/orders", response_model=OrderResponse, status_code=201)
def create_order(data: OrderInput, idempotency_key: Annotated[str, Header(min_length=1, max_length=100)],
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    begin_write(db)
    order = order_service(db).create(user.id, data, idempotency_key)
    db.commit()
    return order


@router.get("/orders", response_model=list[OrderResponse])
def list_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.id.desc())))


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or (order.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "Order not found")
    return order


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(order_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    begin_write(db)
    order = OrderRepository(db).get_owned(order_id, user.id)
    if not order:
        raise HTTPException(404, "Order not found")
    order_service(db).cancel(order)
    db.commit()
    return order


@router.patch("/admin/orders/{order_id}/status", response_model=OrderResponse)
def update_order_status(order_id: int, data: StatusInput, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    begin_write(db)
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if (order.status, data.status) not in {("CONFIRMED", "PREPARING"), ("PREPARING", "DELIVERED")}:
        raise HTTPException(409, "Invalid order status transition")
    order.status = data.status
    db.commit()
    return order
