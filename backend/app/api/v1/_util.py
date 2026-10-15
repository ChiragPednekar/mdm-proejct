from typing import Any

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


class Paging:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def paginate(db: Session, stmt: Select, paging: Paging) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(stmt.limit(paging.page_size).offset(paging.offset)).all()
    return rows, int(total or 0)


def page_body(items: list, total: int, paging: Paging) -> dict:
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}
