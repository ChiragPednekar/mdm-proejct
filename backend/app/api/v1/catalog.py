from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.core.errors import NotFoundError
from app.models import PRODUCT_CATEGORIES, Component, FaultCategory, ProductModel, Technician, User
from app.schemas.common import (
    ComponentIn,
    ComponentOut,
    FaultCategoryOut,
    ProductModelIn,
    ProductModelOut,
    TechnicianIn,
    TechnicianOut,
    TechnicianUpdate,
)
from app.services import audit

router = APIRouter(tags=["catalog"])


@router.get("/catalog/categories", response_model=list[str])
def categories(_: User = Depends(get_current_user)):
    return list(PRODUCT_CATEGORIES)


@router.get("/catalog/manufacturers", response_model=list[str])
def manufacturers(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.scalars(select(ProductModel.manufacturer).distinct().order_by(ProductModel.manufacturer)))


@router.get("/catalog/product-models", response_model=list[ProductModelOut])
def product_models(category: str | None = None, manufacturer: str | None = None,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(ProductModel).order_by(ProductModel.manufacturer, ProductModel.model_name)
    if category:
        stmt = stmt.where(ProductModel.product_category == category)
    if manufacturer:
        stmt = stmt.where(ProductModel.manufacturer == manufacturer)
    return list(db.scalars(stmt))


@router.post("/catalog/product-models", response_model=ProductModelOut, status_code=status.HTTP_201_CREATED)
def create_product_model(body: ProductModelIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    pm = ProductModel(**body.model_dump())
    db.add(pm)
    db.flush()
    audit.log(db, "product_model_created", "product_model", pm.product_model_id, user.user_id)
    db.commit()
    return pm


@router.get("/catalog/fault-categories", response_model=list[FaultCategoryOut])
def fault_categories(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.scalars(select(FaultCategory).order_by(FaultCategory.name)))


@router.get("/catalog/components", response_model=list[ComponentOut])
def components(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return list(db.scalars(select(Component).order_by(Component.component_name)))


@router.post("/catalog/components", response_model=ComponentOut, status_code=status.HTTP_201_CREATED)
def create_component(body: ComponentIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    c = Component(**body.model_dump())
    db.add(c)
    db.flush()
    audit.log(db, "component_created", "component", c.component_id, user.user_id)
    db.commit()
    return c


@router.get("/technicians", response_model=list[TechnicianOut])
def technicians(active_only: bool = False, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    stmt = select(Technician).order_by(Technician.full_name)
    if active_only:
        stmt = stmt.where(Technician.employment_status == "Active")
    return list(db.scalars(stmt))


@router.post("/technicians", response_model=TechnicianOut, status_code=status.HTTP_201_CREATED)
def create_technician(body: TechnicianIn, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    t = Technician(**body.model_dump())
    db.add(t)
    db.flush()
    audit.log(db, "technician_created", "technician", t.technician_id, user.user_id)
    db.commit()
    return t


@router.patch("/technicians/{technician_id}", response_model=TechnicianOut)
def update_technician(technician_id: int, body: TechnicianUpdate, db: Session = Depends(get_db),
                      user: User = Depends(require_roles(*MANAGERS))):
    t = db.get(Technician, technician_id)
    if t is None:
        raise NotFoundError(f"Technician {technician_id} not found.")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for k, v in changes.items():
        setattr(t, k, v)
    audit.log(db, "technician_updated", "technician", technician_id, user.user_id, changes)
    db.commit()
    return t
