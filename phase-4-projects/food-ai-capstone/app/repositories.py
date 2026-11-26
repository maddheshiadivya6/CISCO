from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MenuItem, Order


class MenuReader(Protocol):
    def get(self, item_id: int) -> MenuItem | None: ...

    def get_for_update(self, item_id: int) -> MenuItem | None: ...


class OrderReader(Protocol):
    def find_key(self, user_id: int, key: str) -> Order | None: ...


class MenuRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, item_id: int) -> MenuItem | None:
        return self.db.get(MenuItem, item_id)

    def get_for_update(self, item_id: int) -> MenuItem | None:
        return self.db.scalar(select(MenuItem).where(MenuItem.id == item_id).with_for_update()
                              .execution_options(populate_existing=True))

    def search(self, category=None, vegetarian=None, max_price=None, keyword=None):
        query = select(MenuItem).where(MenuItem.active.is_(True))
        if category:
            query = query.where(MenuItem.category.ilike(f"%{category}%"))
        if vegetarian is not None:
            query = query.where(MenuItem.vegetarian == vegetarian)
        if max_price is not None:
            query = query.where(MenuItem.price <= max_price)
        if keyword:
            query = query.where(MenuItem.title.ilike(f"%{keyword}%"))
        return list(self.db.scalars(query.order_by(MenuItem.id)))


class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_owned(self, order_id: int, user_id: int, for_update: bool = False) -> Order | None:
        query = select(Order).where(Order.id == order_id, Order.user_id == user_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.db.scalar(query)

    def find_key(self, user_id: int, key: str) -> Order | None:
        return self.db.scalar(select(Order).where(Order.user_id == user_id, Order.idempotency_key == key))
