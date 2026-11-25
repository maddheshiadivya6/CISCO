import hashlib
import json
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.errors import DomainError
from app.models import MenuItem, Order, OrderLine
from app.repositories import MenuReader, MenuRepository, OrderReader, OrderRepository
from app.schemas import OrderInput


def begin_write(db: Session):
    db.execute(text("BEGIN IMMEDIATE"))


class OrderService:
    def __init__(self, db: Session, menu: MenuReader, orders: OrderReader):
        self.db = db
        self.menu = menu
        self.orders = orders

    def create(self, user_id: int, data: OrderInput, key: str, expected_prices=None) -> Order:
        canonical = sorted((line.item_id, line.quantity) for line in data.lines)
        if len({item_id for item_id, _ in canonical}) != len(canonical):
            raise DomainError(422, "Each menu item may appear only once")
        digest = hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
        existing = self.orders.find_key(user_id, key)
        if existing:
            if existing.request_hash != digest:
                raise DomainError(409, "Idempotency key already used for a different order")
            return existing
        items = []
        total = Decimal("0")
        for item_id, quantity in canonical:
            item = self.menu.get(item_id)
            if not item or not item.active or item.capacity < quantity:
                raise DomainError(409, f"Item {item_id} is unavailable or has insufficient portions")
            if expected_prices is not None and str(item.price) != expected_prices.get(str(item_id)):
                raise DomainError(409, "Price changed; create a new action and confirm again")
            items.append((item, quantity))
            total += item.price * quantity
        order = Order(user_id=user_id, total=total, idempotency_key=key, request_hash=digest)
        self.db.add(order)
        self.db.flush()
        for item, quantity in items:
            item.capacity -= quantity
            self.db.add(OrderLine(order_id=order.id, item_id=item.id, quantity=quantity, unit_price=item.price))
        self.db.flush()
        self.db.refresh(order)
        return order

    def cancel(self, order: Order):
        if order.status == "CANCELLED":
            return order
        if order.status != "CONFIRMED":
            raise DomainError(409, "Cancellation is only allowed before preparation")
        for line in order.lines:
            item = self.db.get(MenuItem, line.item_id)
            item.capacity += line.quantity
        order.status = "CANCELLED"
        self.db.flush()
        return order


def order_service(db: Session) -> OrderService:
    return OrderService(db, MenuRepository(db), OrderRepository(db))
