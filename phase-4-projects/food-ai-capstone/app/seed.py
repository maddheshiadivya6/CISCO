from decimal import Decimal

from sqlalchemy import select

from app.models import MenuItem, User
from app.schemas import OrderInput
from app.security import hasher
from app.services import begin_write, order_service


def seed(db):
    new_install = db.scalar(select(User.id).limit(1)) is None
    if new_install:
        db.add_all([
            User(username="admin", password_hash=hasher.hash("admin-demo"), role="admin"),
            User(username="alice", password_hash=hasher.hash("alice-demo"), role="user"),
            User(username="bob", password_hash=hasher.hash("bob-demo"), role="user"),
        ])
    if db.scalar(select(MenuItem.id).limit(1)) is None:
        rows = [
            ("Masala Dosa", "Breakfast", True, "90", 20),
            ("Paneer Biryani", "Main course", True, "180", 10),
            ("Idli Sambar", "Breakfast", True, "80", 15),
            ("Veg Thali", "Main course", True, "160", 12),
            ("Dal Tadka", "Main course", True, "140", 15),
            ("Chicken Biryani", "Main course", False, "220", 10),
            ("Egg Curry", "Main course", False, "150", 10),
            ("Roti", "Sides", True, "30", 30),
            ("Mango Lassi", "Drinks", True, "70", 20),
            ("Gulab Jamun", "Dessert", True, "60", 20),
        ]
        db.add_all([MenuItem(title=t, category=c, vegetarian=v, price=Decimal(p), capacity=n) for t, c, v, p, n in rows])
    db.commit()
    if new_install:
        alice = db.scalar(select(User).where(User.username == "alice"))
        bob = db.scalar(select(User).where(User.username == "bob"))
        begin_write(db)
        service = order_service(db)
        for user, item_id, key in [(alice, 1, "seed-1"), (alice, 2, "seed-2"), (bob, 3, "seed-3")]:
            service.create(user.id, OrderInput.model_validate({"lines": [{"item_id": item_id, "quantity": 1}]}), key)
        db.commit()
