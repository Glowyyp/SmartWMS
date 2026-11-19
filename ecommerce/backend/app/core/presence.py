"""
core/presence.py — Seguimiento de estado de conexión y última actividad de usuarios.
"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.user import User

ONLINE_TTL_SECONDS = 35   # 35 segundos sin actividad/heartbeat marca al usuario como desconectado
TOUCH_THROTTLE_SECONDS = 15


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_user_online(user: User) -> bool:
    """Devuelve True si el usuario tiene sesión activa y actividad reciente."""
    if not getattr(user, "is_connected", False):
        return False
    last_seen = _as_utc(getattr(user, "last_seen_at", None))
    if last_seen is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
    return elapsed <= ONLINE_TTL_SECONDS


def mark_user_connected(user: User, is_login: bool = False) -> None:
    """Marca al usuario como conectado y actualiza timestamps de conexión."""
    now = datetime.now(timezone.utc)
    user.is_connected = True
    user.last_seen_at = now
    if is_login:
        user.last_login_at = now


def touch_user_activity(user: User, db: Session) -> None:
    """Actualiza last_seen_at de forma throttled para no escribir en cada request."""
    now = datetime.now(timezone.utc)
    last_seen = _as_utc(getattr(user, "last_seen_at", None))
    if not getattr(user, "is_connected", False) or last_seen is None or (now - last_seen).total_seconds() >= TOUCH_THROTTLE_SECONDS:
        user.is_connected = True
        user.last_seen_at = now
        db.commit()
