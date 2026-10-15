from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import Paging, page_body, paginate
from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.core.errors import ConflictError, NotFoundError
from app.models import Customer, Product, ServiceRequest, User
from app.schemas.common import CustomerIn, CustomerOut, CustomerUpdate
from app.services import audit

router = APIRouter(prefix="/customers", tags=["customers"])


def _with_counts():
    products = (select(func.count(Product.product_id)).where(Product.customer_id == Customer.customer_id)
                .correlate(Customer).scalar_subquery())
    requests = (select(func.count(ServiceRequest.service_request_id))
                .join(Product, Product.product_id == ServiceRequest.product_id)
                .where(Product.customer_id == Customer.customer_id).correlate(Customer).scalar_subquery())
    return select(Customer, products.label("product_count"), requests.label("service_request_count"))


def _out(row) -> CustomerOut:
    c, pc, rc = row
    return CustomerOut.model_validate(c).model_copy(update={"product_count": pc, "service_request_count": rc})


@router.get("")
def list_customers(
    q: str | None = Query(None, max_length=100, description="Name, email or phone"),
    city: str | None = None,
    sort: str = Query("name", pattern="^(name|newest|requests)$"),
    paging: Paging = Depends(),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    stmt = _with_counts()
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(Customer.full_name).like(like), func.lower(Customer.email).like(like),
                              Customer.phone.like(f"%{q.strip()}%")))
    if city:
        stmt = stmt.where(Customer.city == city)
    order = {"name": Customer.full_name, "newest": Customer.created_at.desc(),
             "requests": stmt.selected_columns.service_request_count.desc()}[sort]
    rows, total = paginate(db, stmt.order_by(order, Customer.customer_id), paging)
    return page_body([_out(r) for r in rows], total, paging)


@router.get("/cities", response_model=list[str])
def cities(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [c for c in db.scalars(select(Customer.city).where(Customer.city.is_not(None)).distinct().order_by(Customer.city))]


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(body: CustomerIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = Customer(**body.model_dump())
    db.add(c)
    db.flush()
    audit.log(db, "customer_created", "customer", c.customer_id, user.user_id)
    db.commit()
    return CustomerOut.model_validate(c).model_copy(update={"product_count": 0, "service_request_count": 0})


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = db.execute(_with_counts().where(Customer.customer_id == customer_id)).first()
    if row is None:
        raise NotFoundError(f"Customer {customer_id} not found.")
    return _out(row)


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerUpdate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    c = db.get(Customer, customer_id)
    if c is None:
        raise NotFoundError(f"Customer {customer_id} not found.")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(c, k, v.strip() if isinstance(v, str) else v)
    db.flush()  # CHECK constraint enforces that a contact method remains
    audit.log(db, "customer_updated", "customer", customer_id, user.user_id, {"fields": sorted(changes)})
    db.commit()
    return get_customer(customer_id, db, user)


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(customer_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    c = db.get(Customer, customer_id)
    if c is None:
        raise NotFoundError(f"Customer {customer_id} not found.")
    if db.scalar(select(func.count()).where(Product.customer_id == customer_id)):
        raise ConflictError("Customer owns registered products; reassign or retire them first.")
    db.delete(c)
    audit.log(db, "customer_deleted", "customer", customer_id, user.user_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
