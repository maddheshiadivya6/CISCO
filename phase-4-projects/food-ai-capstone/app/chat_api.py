import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.security import HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import respond
from app.database import get_db
from app.errors import DomainError
from app.models import ChatMessage, ChatSession, PendingAction, ToolRun, User, utcnow
from app.rag import MAX_BYTES, index_document
from app.repositories import OrderRepository
from app.schemas import ConfirmInput, MessageInput, OrderInput, OrderResponse, SessionInput
from app.security import admin_user, current_user, security
from app.services import begin_write, order_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def owned_session(db: Session, session_id: int, user_id: int) -> ChatSession:
    session = db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id))
    if session is None:
        raise HTTPException(404, "Chat session not found")
    return session


def message_dict(message: ChatMessage) -> dict:
    return {"id": message.id, "seq_no": message.seq_no, "role": message.role,
            "content": message.content, "details": message.details, "created_at": message.created_at}


def add_message(db: Session, session_id: int, role: str, content: str, details: dict) -> ChatMessage:
    db.scalar(select(ChatSession.id).where(ChatSession.id == session_id).with_for_update())
    seq = db.scalar(select(func.max(ChatMessage.seq_no)).where(ChatMessage.session_id == session_id)) or 0
    message = ChatMessage(session_id=session_id, seq_no=seq + 1, role=role, content=content, details=details)
    db.add(message)
    db.flush()
    return message


def action_dict(action: PendingAction) -> dict:
    return {"id": action.id, "action": action.action, "payload": action.payload,
            "status": action.status, "expires_at": action.expires_at, "result": action.result}


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), user: User = Depends(admin_user),
                          db: Session = Depends(get_db)):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Document exceeds 5 MiB")
    return index_document(db, file.filename or "", data, user.id)


@router.post("/chat/sessions", status_code=201)
def create_session(data: SessionInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    session = ChatSession(user_id=user.id, title=data.title)
    db.add(session)
    db.commit()
    return {"id": session.id, "title": session.title, "created_at": session.created_at}


@router.get("/chat/sessions")
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sessions = db.scalars(select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.id.desc()))
    return [{"id": s.id, "title": s.title, "created_at": s.created_at} for s in sessions]


@router.get("/chat/sessions/{session_id}/messages")
def messages(session_id: int, after: int = 0, limit: int = 50,
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    if after < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid pagination")
    owned_session(db, session_id, user.id)
    items = db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id, ChatMessage.seq_no > after)
                       .order_by(ChatMessage.seq_no).limit(limit))
    actions = db.scalars(select(PendingAction).where(PendingAction.session_id == session_id,
                                                     PendingAction.user_id == user.id).order_by(PendingAction.id.desc()))
    return {"messages": [message_dict(m) for m in items], "actions": [action_dict(a) for a in actions]}


@router.post("/chat/sessions/{session_id}/messages")
async def send_message(session_id: int, data: MessageInput, request: Request,
                       user: User = Depends(current_user), credentials: HTTPBasicCredentials = Depends(security),
                       db: Session = Depends(get_db)):
    owned_session(db, session_id, user.id)
    begin_write(db)
    add_message(db, session_id, "user", data.message, {})
    db.commit()
    recent = list(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id)
                             .order_by(ChatMessage.seq_no.desc()).limit(12)))
    history = [{"role": m.role, "content": m.content} for m in reversed(recent)]
    audit = []
    try:
        text, mode, citations, actions = await respond(
            db, request, (credentials.username, credentials.password), user.id, session_id, history, audit)
    except HTTPException as exc:
        db.rollback()
        begin_write(db)
        message = add_message(db, session_id, "assistant", str(exc.detail), {"mode": "ERROR", "citations": []})
        for run in audit:
            db.add(ToolRun(message_id=message.id, **run))
        db.commit()
        raise
    except Exception:
        logger.exception("Unexpected error while processing chat")
        db.rollback()
        begin_write(db)
        message = add_message(db, session_id, "assistant", "Unable to process this message.",
                              {"mode": "ERROR", "citations": []})
        for run in audit:
            db.add(ToolRun(message_id=message.id, **run))
        db.commit()
        raise
    begin_write(db)
    message = add_message(db, session_id, "assistant", text,
                          {"mode": mode, "citations": citations, "action_ids": actions})
    for run in audit:
        db.add(ToolRun(message_id=message.id, **run))
    db.commit()
    return message_dict(message)


@router.post("/chat/actions/{action_id}/confirm")
def confirm_action(action_id: int, data: ConfirmInput, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    begin_write(db)
    action = db.scalar(select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user.id)
                       .with_for_update().execution_options(populate_existing=True))
    if not action:
        raise HTTPException(404, "Action not found")
    if action.status == "CONFIRMED" and data.confirm:
        return action_dict(action)
    if action.status == "REJECTED" and not data.confirm:
        return action_dict(action)
    if action.status != "PENDING":
        raise HTTPException(409, f"Action is {action.status.lower()}")
    if action.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        action.status = "EXPIRED"
        db.commit()
        raise HTTPException(409, "Action expired")
    if not data.confirm:
        action.status = "REJECTED"
        action.result = {"message": "Action rejected; no change was made"}
    else:
        service = order_service(db)
        try:
            if action.action == "CREATE":
                lines = action.payload["lines"]
                order = service.create(user.id, OrderInput.model_validate({"lines": [
                    {"item_id": line["item_id"], "quantity": line["quantity"]} for line in lines
                ]}), f"agent-action-{action.id}",
                    {str(line["item_id"]): str(line["unit_price"]) for line in lines})
            elif action.action == "CANCEL":
                order = OrderRepository(db).get_owned(action.payload["order_id"], user.id, for_update=True)
                if not order:
                    raise HTTPException(404, "Order not found")
                if order.status != action.payload["status"]:
                    raise HTTPException(409, "Order status changed; review it again")
                service.cancel(order)
            else:
                raise HTTPException(409, "Unknown action")
        except (HTTPException, DomainError):
            db.rollback()
            raise
        action.status = "CONFIRMED"
        action.result = OrderResponse.model_validate(order).model_dump(mode="json")
    add_message(db, action.session_id, "assistant",
                "Action confirmed." if data.confirm else "Action rejected.",
                {"mode": "AGENT", "citations": [], "action_id": action.id, "result": action.result})
    db.commit()
    return action_dict(action)
