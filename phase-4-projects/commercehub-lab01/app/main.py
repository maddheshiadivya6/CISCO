from fastapi import Depends, FastAPI, status

from app.models import OrderRequest, OrderResponse
from app.repository import InMemoryOrderRepository
from app.service import OrderService

app = FastAPI(title="CommerceHub Order Management API")
repository = InMemoryOrderRepository()


def get_order_service() -> OrderService:
    return OrderService(repository)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    request: OrderRequest,
    service: OrderService = Depends(get_order_service),
):
    return service.create_order(request)


@app.get("/orders", response_model=list[OrderResponse])
def list_orders(service: OrderService = Depends(get_order_service)):
    return service.list_orders()
