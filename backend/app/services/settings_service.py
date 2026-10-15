from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULTS: dict[str, Any] = {
    "risk_band_medium_min": 0.30,
    "risk_band_high_min": 0.60,
    "prediction_horizon_days": 30,
    "repeat_failure_window_days": 90,
    "expiring_soon_days": 60,
    "dataset_provenance": "operational",
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    return row.setting_value if row is not None else DEFAULTS.get(key)


def all_settings(db: Session) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for row in db.query(AppSetting).all():
        out[row.setting_key] = row.setting_value
    return out


def set_setting(db: Session, key: str, value: Any, description: str | None = None) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(setting_key=key, setting_value=value, description=description))
    else:
        row.setting_value = value


def risk_level(db: Session, probability: float) -> str:
    medium = float(get_setting(db, "risk_band_medium_min"))
    high = float(get_setting(db, "risk_band_high_min"))
    if probability >= high:
        return "High"
    if probability >= medium:
        return "Medium"
    return "Low"
