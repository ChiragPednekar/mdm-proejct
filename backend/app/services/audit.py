from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def log(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    user_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Add an audit record to the current transaction (committed with it)."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            details=details,
        )
    )
