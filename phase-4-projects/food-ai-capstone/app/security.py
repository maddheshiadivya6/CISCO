import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

security = HTTPBasic()
hasher = PasswordHasher()
dummy_hash = hasher.hash("not-a-real-password")


def current_user(
    credentials: HTTPBasicCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    user = db.scalar(select(User).where(User.username == credentials.username))
    try:
        valid = hasher.verify(user.password_hash if user else dummy_hash, credentials.password)
    except (VerifyMismatchError, InvalidHashError):
        valid = False
    if not valid or user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials", headers={"WWW-Authenticate": "Basic"})
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not secrets.compare_digest(user.role, "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user
