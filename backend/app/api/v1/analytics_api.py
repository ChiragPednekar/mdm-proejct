from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import MANAGERS, get_current_user, require_roles
from app.models import User
from app.services import analytics, settings_service
from app.schemas.common import SettingsUpdate
from app.core.errors import BusinessRuleError
from app.services import audit
from app.services.analytics import _rows

router = APIRouter(tags=["analytics"])


@router.get("/dashboard/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return analytics.dashboard_summary(db)


@router.get("/dashboard/trends")
def trends(months: int = Query(12, ge=3, le=36), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return analytics.dashboard_trends(db, months)


@router.get("/analytics/reports")
def reports(_: User = Depends(get_current_user)):
    return analytics.report_catalog()


@router.get("/analytics/{report_name}")
def run_report(report_name: str, request: Request, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return analytics.run_report(db, report_name, dict(request.query_params))


@router.get("/settings")
def get_settings_(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return settings_service.all_settings(db)


@router.put("/settings")
def put_settings(body: SettingsUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    changes = body.model_dump(exclude_none=True)
    current = settings_service.all_settings(db)
    medium = changes.get("risk_band_medium_min", current["risk_band_medium_min"])
    high = changes.get("risk_band_high_min", current["risk_band_high_min"])
    if float(medium) >= float(high):
        raise BusinessRuleError("The Medium band must start below the High band.")
    for k, v in changes.items():
        settings_service.set_setting(db, k, v)
    audit.log(db, "settings_updated", "app_settings", None, user.user_id, changes)
    db.commit()
    return settings_service.all_settings(db)


@router.get("/audit-logs")
def audit_logs(entity_type: str | None = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
               _: User = Depends(require_roles(*MANAGERS))):
    where = "WHERE a.entity_type = :et" if entity_type else ""
    return _rows(db, f"""
        SELECT a.audit_log_id, a.timestamp, a.action, a.entity_type, a.entity_id, a.details, u.username
        FROM audit_logs a LEFT JOIN users u ON u.user_id = a.user_id {where}
        ORDER BY a.timestamp DESC, a.audit_log_id DESC LIMIT :limit""", {"et": entity_type, "limit": limit})
