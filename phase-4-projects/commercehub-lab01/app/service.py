from app.models import OrderItem, OrderRequest, OrderResponse
from app.repository import OrderRepository


class OrderService:
    def __init__(self, repository: OrderRepository):
        self.repository = repository

    def calculate_total(self, items: list[OrderItem]) -> float:
        return round(sum(item.quantity * item.unit_price for item in items), 2)

    def create_order(self, request: OrderRequest) -> OrderResponse:
        total = self.calculate_total(request.items)
        saved_order = self.repository.save({
            "customer_name": request.customer_name,
            "items": [item.model_dump() for item in request.items],
            "total": total,
        })
        return OrderResponse(**saved_order)

    def list_orders(self) -> list[OrderResponse]:
        return [OrderResponse(**order) for order in self.repository.list_all()]
