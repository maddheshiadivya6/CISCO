from typing import Any, Protocol


class OrderRepository(Protocol):
    def save(self, order: dict[str, Any]) -> dict[str, Any]:
        ...

    def list_all(self) -> list[dict[str, Any]]:
        ...


class InMemoryOrderRepository:
    def __init__(self):
        self._orders = []
        self._next_order_id = 1

    def save(self, order: dict[str, Any]) -> dict[str, Any]:
        saved_order = {"order_id": self._next_order_id, **order}
        self._next_order_id += 1
        self._orders.append(saved_order)
        return saved_order

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._orders)
