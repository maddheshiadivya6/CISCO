from app.models import OrderItem, OrderRequest
from app.repository import InMemoryOrderRepository
from app.service import OrderService


def test_calculate_total_for_multiple_items():
    service = OrderService(InMemoryOrderRepository())
    items = [
        OrderItem(name="Notebook", quantity=2, unit_price=50),
        OrderItem(name="Pen", quantity=1, unit_price=20),
    ]

    assert service.calculate_total(items) == 120.0


def test_created_order_can_be_listed():
    service = OrderService(InMemoryOrderRepository())
    request = OrderRequest(
        customer_name="Anu",
        items=[
            OrderItem(name="Notebook", quantity=2, unit_price=50),
            OrderItem(name="Pen", quantity=1, unit_price=20),
        ],
    )

    created_order = service.create_order(request)

    assert created_order.order_id == 1
    assert created_order.total == 120.0
    assert service.list_orders() == [created_order]