"""Authentication / authorization dependencies."""
from collections.abc import Callable

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AuthError, ForbiddenError
from app.core.security import decode_access_token
from app.models import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise AuthError("Authentication required.")
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise AuthError("Invalid or expired token.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive.")
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise ForbiddenError(f"This action requires one of the roles: {', '.join(roles)}.")
        return user

    return _check


MANAGERS = ("admin", "service_manager")
