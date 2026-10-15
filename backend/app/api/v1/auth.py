from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.errors import AuthError
from app.core.security import create_access_token, verify_password
from app.models import User
from app.schemas.common import LoginIn, TokenOut, UserOut
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise AuthError("Invalid username or password.")
    audit.log(db, "user_login", "user", user.user_id, user.user_id)
    db.commit()
    return TokenOut(access_token=create_access_token(user.user_id, user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
