from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from sqlalchemy import select

import app.agent as agent_module
import app.rag as rag_module
from app.database import SessionLocal
from app.main import app
from app.models import ChatMessage, PendingAction, ToolRun, User

ALICE = ("alice", "alice-demo")
BOB = ("bob", "bob-demo")
ADMIN = ("admin", "admin-demo")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as client:
        yield client


def create_order(client, auth=ALICE, key="order-1", item_id=1, quantity=1):
    return client.post("/api/orders", auth=auth, headers={"Idempotency-Key": key},
                       json={"lines": [{"item_id": item_id, "quantity": quantity}]})


def test_menu_and_authorization(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert len(client.get("/api/menu_items").json()) >= 10
    nonveg = client.get("/api/menu_items", params={"vegetarian": "false"}).json()
    assert nonveg and all(not item["vegetarian"] for item in nonveg)
    assert client.post("/api/menu_items", auth=ALICE, json={
        "title": "New dish", "category": "Main", "vegetarian": True, "price": "10", "capacity": 1,
    }).status_code == 403
    assert client.get("/api/orders").status_code == 401


def test_order_idempotency_ownership_and_cancellation(client):
    before = client.get("/api/menu_items/1").json()["capacity"]
    first = create_order(client)
    assert first.status_code == 201, first.text
    order = first.json()
    assert order["total"] == "90.00"
    assert create_order(client).json()["id"] == order["id"]
    assert create_order(client, key="order-1", quantity=2).status_code == 409
    assert client.get(f"/api/orders/{order['id']}", auth=BOB).status_code == 404
    assert client.post(f"/api/orders/{order['id']}/cancel", auth=BOB).status_code == 404
    assert client.post(f"/api/orders/{order['id']}/cancel", auth=ALICE).json()["status"] == "CANCELLED"
    assert client.post(f"/api/orders/{order['id']}/cancel", auth=ALICE).status_code == 200
    assert client.get("/api/menu_items/1").json()["capacity"] == before


def test_status_transition_and_validation(client):
    order = create_order(client, key="status-test").json()
    path = f"/api/admin/orders/{order['id']}/status"
    assert client.patch(path, auth=ALICE, json={"status": "PREPARING"}).status_code == 403
    assert client.patch(path, auth=ADMIN, json={"status": "DELIVERED"}).status_code == 409
    assert client.patch(path, auth=ADMIN, json={"status": "PREPARING"}).status_code == 200
    assert client.post(f"/api/orders/{order['id']}/cancel", auth=ALICE).status_code == 409
    assert create_order(client, key="bad", quantity=11).status_code == 422


def test_concurrent_last_portion(client):
    item = client.post("/api/menu_items", auth=ADMIN, json={
        "title": "Last portion", "category": "Main", "vegetarian": True, "price": "40", "capacity": 1,
    }).json()
    def buy(n):
        return create_order(client, key=f"last-{n}", item_id=item["id"]).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(buy, [1, 2]))
    assert statuses == [201, 409]
    assert client.get(f"/api/menu_items/{item['id']}").json()["capacity"] == 0


def test_chat_owner_and_missing_gemini_persisted(client):
    session = client.post("/api/chat/sessions", auth=ALICE, json={"title": "Test"}).json()
    url = f"/api/chat/sessions/{session['id']}/messages"
    assert client.get(url, auth=BOB).status_code == 404
    result = client.post(url, auth=ALICE, json={"message": "Show non-vegetarian food"})
    assert result.status_code == 503
    messages = client.get(url, auth=ALICE).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[-1]["details"]["mode"] == "ERROR"


def test_pending_action_confirmation(client):
    session = client.post("/api/chat/sessions", auth=ALICE, json={"title": "Action"}).json()
    item = client.get("/api/menu_items/2").json()
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "alice"))
        action = PendingAction(session_id=session["id"], user_id=user_id, action="CREATE",
                               payload={"lines": [{"item_id": item["id"], "title": item["title"],
                                                   "quantity": 1, "unit_price": item["price"]}]},
                               expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add(action); db.commit(); action_id = action.id
    url = f"/api/chat/actions/{action_id}/confirm"
    assert client.post(url, auth=BOB, json={"confirm": True}).status_code == 404
    first = client.post(url, auth=ALICE, json={"confirm": True})
    assert first.status_code == 200, first.text
    assert first.json()["result"]["status"] == "CONFIRMED"
    assert client.post(url, auth=ALICE, json={"confirm": True}).json()["result"] == first.json()["result"]
    assert client.post(url, auth=ALICE, json={"confirm": False}).status_code == 409


def test_agent_tools_and_confirmation(client, monkeypatch):
    class FakeModels:
        def __init__(self):
            self.count = 0

        def generate_content(self, **kwargs):
            self.count += 1
            if self.count == 1:
                parts = [
                    types.Part(function_call=types.FunctionCall(name="search_menu", args={"vegetarian": False})),
                    types.Part(function_call=types.FunctionCall(name="list_orders", args={})),
                ]
            elif self.count == 2:
                parts = [types.Part(function_call=types.FunctionCall(
                    name="prepare_order", args={"lines": [{"item_id": 6, "quantity": 1}]}))]
            else:
                parts = [types.Part(text="Please review and confirm the order.")]
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=parts))])

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(agent_module, "client", lambda: FakeClient())
    session = client.post("/api/chat/sessions", auth=ALICE, json={"title": "Agent"}).json()
    before = len(client.get("/api/orders", auth=ALICE).json())
    response = client.post(f"/api/chat/sessions/{session['id']}/messages", auth=ALICE,
                           json={"message": "List non-vegetarian food and order chicken biryani"})
    assert response.status_code == 200, response.text
    assert response.json()["details"]["mode"] == "AGENT"
    with SessionLocal() as db:
        runs = list(db.scalars(select(ToolRun).where(ToolRun.message_id == response.json()["id"])))
        assert {run.tool_name for run in runs} == {"search_menu", "list_orders", "prepare_order"}
    assert len(client.get("/api/orders", auth=ALICE).json()) == before
    action_id = response.json()["details"]["action_ids"][0]
    action = client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True})
    assert action.status_code == 200, action.text
    assert len(client.get("/api/orders", auth=ALICE).json()) == before + 1
    assert client.post(f"/api/chat/actions/{action_id}/confirm", auth=ALICE, json={"confirm": True}).status_code == 200
    assert len(client.get("/api/orders", auth=ALICE).json()) == before + 1


def test_rejection_expiry_and_changed_price(client):
    session_id = client.post("/api/chat/sessions", auth=ALICE, json={"title": "Reject"}).json()["id"]
    item = client.get("/api/menu_items/2").json()
    def create_action(expiry, price):
        with SessionLocal() as db:
            user_id = db.scalar(select(User.id).where(User.username == "alice"))
            action = PendingAction(session_id=session_id, user_id=user_id, action="CREATE",
                payload={"lines": [{"item_id": item["id"], "title": item["title"], "quantity": 1, "unit_price": price}]},
                expires_at=expiry)
            db.add(action); db.commit()
            return action.id
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    rejected = create_action(future, item["price"])
    url = f"/api/chat/actions/{rejected}/confirm"
    assert client.post(url, auth=ALICE, json={"confirm": False}).json()["status"] == "REJECTED"
    assert client.post(url, auth=ALICE, json={"confirm": True}).status_code == 409
    expired = create_action(datetime.now(timezone.utc) - timedelta(minutes=1), item["price"])
    assert client.post(f"/api/chat/actions/{expired}/confirm", auth=ALICE, json={"confirm": True}).status_code == 409
    changed = create_action(future, "0.01")
    assert client.post(f"/api/chat/actions/{changed}/confirm", auth=ALICE, json={"confirm": True}).status_code == 409


def test_document_index_and_retrieval(client, monkeypatch):
    monkeypatch.setattr(rag_module, "embed", lambda texts, task_type: [[1.0, 0.0] for _ in texts])
    response = client.post("/api/documents", auth=ADMIN,
                           files={"file": ("policy.txt", b"Cancellation before preparation only.", "text/plain")})
    assert response.status_code == 201, response.text
    assert response.json()["chunks"] == 1
    with SessionLocal() as db:
        results = rag_module.retrieve(db, "Can I cancel?")
    assert results[0]["filename"] == "policy.txt"
    assert results[0]["page"] == "section 1"
    assert "Cancellation" in results[0]["text"]
    assert client.post("/api/documents", auth=ALICE,
                       files={"file": ("policy.txt", b"text", "text/plain")}).status_code == 403


def test_mixed_agent_cites_policy_and_audits_tools(client, monkeypatch):
    class FakeModels:
        calls = 0

        def generate_content(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                parts = [
                    types.Part(function_call=types.FunctionCall(name="search_menu", args={"vegetarian": True})),
                    types.Part(function_call=types.FunctionCall(name="retrieve_policy", args={"question": "cancellation"})),
                ]
            else:
                parts = [types.Part(text="Cancellation is allowed before preparation.")]
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=parts))])

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(agent_module, "client", lambda: FakeClient())
    monkeypatch.setattr(rag_module, "embed", lambda texts, task_type: [[1.0, 0.0] for _ in texts])
    session_id = client.post("/api/chat/sessions", auth=ALICE, json={"title": "Mixed"}).json()["id"]
    response = client.post(f"/api/chat/sessions/{session_id}/messages", auth=ALICE,
                           json={"message": "Show vegetarian food and cancellation policy"})
    assert response.status_code == 200, response.text
    details = response.json()["details"]
    assert details["mode"] == "MIXED"
    assert details["citations"][0]["filename"] == "policy.txt"
    with SessionLocal() as db:
        runs = list(db.scalars(select(ToolRun).where(ToolRun.message_id == response.json()["id"])))
        assert {run.tool_name for run in runs} == {"search_menu", "retrieve_policy"}


def test_policy_embedding_error_is_persisted(client, monkeypatch):
    from fastapi import HTTPException

    class FakeModels:
        def generate_content(self, **kwargs):
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=[
                    types.Part(function_call=types.FunctionCall(name="retrieve_policy", args={"question": "policy"}))
                ]))])

    class FakeClient:
        models = FakeModels()

    def fail(*args):
        raise HTTPException(503, "Embedding unavailable")

    monkeypatch.setattr(agent_module, "client", lambda: FakeClient())
    monkeypatch.setattr(agent_module, "retrieve", fail)
    session_id = client.post("/api/chat/sessions", auth=ALICE, json={"title": "Error"}).json()["id"]
    response = client.post(f"/api/chat/sessions/{session_id}/messages", auth=ALICE, json={"message": "Policy?"})
    assert response.status_code == 503
    with SessionLocal() as db:
        message = db.scalar(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.role == "assistant"))
        assert message.details["mode"] == "ERROR"
        assert db.scalar(select(ToolRun).where(ToolRun.message_id == message.id)).status == "ERROR"
