"""
core/presence.py — Seguimiento de estado de conexión, sesiones históricas y detección de desconexiones.

Reglas de precisión para el tiempo de uso:
  1. Cada inicio de sesión (directo o tras completar MFA) abre un registro en `user_sessions`.
  2. Las peticiones autenticadas y los heartbeats periódicos actualizan `last_activity_at`.
  3. Al cerrar sesión explícitamente (`/api/auth/logout`), se cierra la sesión con `ended_at = now`
     y `status = 'closed'`.
  4. Si un usuario cierra la app abruptamente, pierde internet o deja de usar el sistema sin
     cerrar sesión, al superar `SESSION_TIMEOUT_SECONDS` sin actividad la sesión se cierra
     automáticamente con `status = 'timeout'` y `ended_at = last_activity_at` (NUNCA `now`),
     evitando contabilizar horas fantasma mientras el usuario estuvo desconectado.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_session import UserSession

SESSION_TIMEOUT_SECONDS = int(os.getenv("SESSION_TIMEOUT_SECONDS", "90"))
ONLINE_TTL_SECONDS = SESSION_TIMEOUT_SECONDS
TOUCH_THROTTLE_SECONDS = 15


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def detect_client_type(request: Request | None) -> str:
    """Identifica si la sesión proviene de 'mobile', 'web' o 'api'."""
    if request is None:
        return "web"
    explicit = (request.headers.get("x-client-type") or "").strip().lower()
    if explicit in ("mobile", "web", "api"):
        return explicit
    ua = (request.headers.get("user-agent") or "").lower()
    if any(tok in ua for tok in ("okhttp", "android", "dalvik", "smartwms-android")):
        return "mobile"
    if any(tok in ua for tok in ("mozilla", "chrome", "safari", "firefox", "edg")):
        return "web"
    return "api"


def extract_client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return None


def compute_session_duration_seconds(
    session: UserSession,
    now: datetime | None = None,
) -> int:
    """
    Calcula la duración real de una sesión en segundos.
    - Si está cerrada/timeout: usa ended_at - started_at (o duration_seconds persistido).
    - Si está activa pero venció el timeout: acota hasta last_activity_at para no inflar horas.
    - Si está activa y vigente: calcula now - started_at.
    """
    ref_now = _as_utc(now) or datetime.now(timezone.utc)
    started = _as_utc(session.started_at)
    if started is None:
        return max(0, int(session.duration_seconds or 0))

    if session.ended_at is not None:
        ended = _as_utc(session.ended_at)
        return max(0, int((ended - started).total_seconds()))

    last_act = _as_utc(session.last_activity_at) or started
    if (ref_now - last_act).total_seconds() > SESSION_TIMEOUT_SECONDS:
        return max(0, int((last_act - started).total_seconds()))

    return max(0, int((ref_now - started).total_seconds()))


def is_session_effectively_online(
    session: UserSession,
    now: datetime | None = None,
) -> bool:
    if session.status != "active" or session.ended_at is not None:
        return False
    ref_now = _as_utc(now) or datetime.now(timezone.utc)
    last_act = _as_utc(session.last_activity_at)
    if last_act is None:
        return False
    return (ref_now - last_act).total_seconds() <= SESSION_TIMEOUT_SECONDS


def compute_user_online(user: User, now: datetime | None = None) -> bool:
    """Devuelve True si el usuario tiene sesión activa y actividad reciente."""
    if not getattr(user, "is_connected", False):
        return False
    last_seen = _as_utc(getattr(user, "last_seen_at", None))
    if last_seen is None:
        return False
    ref_now = _as_utc(now) or datetime.now(timezone.utc)
    elapsed = (ref_now - last_seen).total_seconds()
    return elapsed <= ONLINE_TTL_SECONDS


def reconcile_stale_sessions(
    db: Session,
    user_id: int | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> int:
    """
    Detecta sesiones marcadas como 'active' que superaron SESSION_TIMEOUT_SECONDS sin
    actividad y las cierra con ended_at = last_activity_at (status = 'timeout').
    Sincroniza también User.is_connected para evitar inconsistencias.
    """
    ref_now = _as_utc(now) or datetime.now(timezone.utc)
    q = db.query(UserSession).filter(UserSession.status == "active")
    if user_id is not None:
        q = q.filter(UserSession.user_id == user_id)

    active_sessions = q.all()
    closed_count = 0
    affected_user_ids: set[int] = set()
    still_active_user_ids: set[int] = set()

    for sess in active_sessions:
        last_act = _as_utc(sess.last_activity_at) or _as_utc(sess.started_at) or ref_now
        elapsed = (ref_now - last_act).total_seconds()
        if elapsed > SESSION_TIMEOUT_SECONDS:
            started = _as_utc(sess.started_at) or last_act
            sess.ended_at = last_act
            sess.duration_seconds = max(0, int((last_act - started).total_seconds()))
            sess.status = "timeout"
            sess.disconnect_reason = "inactivity_timeout"
            closed_count += 1
            affected_user_ids.add(sess.user_id)
        else:
            still_active_user_ids.add(sess.user_id)

    dirty = closed_count > 0

    # Actualizar User.is_connected para usuarios que perdieron todas sus sesiones activas
    disconnected_ids = affected_user_ids - still_active_user_ids
    if disconnected_ids:
        users_to_disconnect = db.query(User).filter(User.id.in_(disconnected_ids)).all()
        for u in users_to_disconnect:
            if u.is_connected:
                u.is_connected = False
                dirty = True

    # Limpiar usuarios marcados is_connected=True que expiraron sin sesión activa
    u_query = db.query(User).filter(User.is_connected == True)  # noqa: E712
    if user_id is not None:
        u_query = u_query.filter(User.id == user_id)
    for u in u_query.all():
        if u.id in still_active_user_ids:
            continue
        last_seen = _as_utc(u.last_seen_at)
        if last_seen is None or (ref_now - last_seen).total_seconds() > ONLINE_TTL_SECONDS:
            u.is_connected = False
            dirty = True

    if dirty and commit:
        db.commit()
    return closed_count


def mark_user_connected(user: User, is_login: bool = False) -> None:
    """Marca al usuario como conectado y actualiza timestamps de conexión."""
    now = datetime.now(timezone.utc)
    user.is_connected = True
    user.last_seen_at = now
    if is_login:
        user.last_login_at = now


def open_user_session(
    user: User,
    db: Session,
    client_type: str = "web",
    ip_address: str | None = None,
    now: datetime | None = None,
) -> str:
    """
    Registra el inicio de una nueva sesión histórica para el usuario y devuelve
    el identificador `jti` para incrustar en el JWT.
    Cierra sesiones vencidas y reemplaza sesiones previas abiertas en el mismo tipo de cliente
    para evitar registros duplicados o superpuestos.
    """
    ref_now = _as_utc(now) or datetime.now(timezone.utc)
    reconcile_stale_sessions(db, user_id=user.id, now=ref_now, commit=False)

    # Si ya existe una sesión activa en el mismo cliente (ej. nuevo login sin logout previo), cerrarla
    existing_same_client = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user.id,
            UserSession.status == "active",
            UserSession.client_type == client_type,
        )
        .all()
    )
    for prev in existing_same_client:
        started = _as_utc(prev.started_at) or ref_now
        prev_end = _as_utc(prev.last_activity_at) or ref_now
        if prev_end > ref_now:
            prev_end = ref_now
        prev.ended_at = prev_end
        prev.duration_seconds = max(0, int((prev_end - started).total_seconds()))
        prev.status = "closed"
        prev.disconnect_reason = "new_login"

    jti = uuid.uuid4().hex
    session = UserSession(
        user_id=user.id,
        session_token_id=jti,
        client_type=client_type,
        ip_address=ip_address,
        started_at=ref_now,
        last_activity_at=ref_now,
        ended_at=None,
        duration_seconds=0,
        status="active",
        disconnect_reason=None,
    )
    db.add(session)

    user.is_connected = True
    user.last_login_at = ref_now
    user.last_seen_at = ref_now
    return jti


def close_user_session(
    user: User,
    db: Session,
    jti: str | None = None,
    reason: str = "logout",
    now: datetime | None = None,
) -> Optional[UserSession]:
    """
    Cierra explícitamente la sesión correspondiente al token JWT (`jti`) o la sesión activa
    más reciente del usuario, registrando hora de cierre y duración exacta.
    """
    ref_now = _as_utc(now) or datetime.now(timezone.utc)
    reconcile_stale_sessions(db, user_id=user.id, now=ref_now, commit=False)

    target: UserSession | None = None
    if jti:
        target = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user.id,
                UserSession.session_token_id == jti,
                UserSession.status == "active",
            )
            .order_by(UserSession.started_at.desc())
            .first()
        )
    if target is None:
        target = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user.id,
                UserSession.status == "active",
            )
            .order_by(UserSession.started_at.desc())
            .first()
        )

    if target is not None:
        started = _as_utc(target.started_at) or ref_now
        target.last_activity_at = ref_now
        target.ended_at = ref_now
        target.duration_seconds = max(0, int((ref_now - started).total_seconds()))
        target.status = "closed"
        target.disconnect_reason = reason

    remaining_active = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user.id,
            UserSession.status == "active",
        )
        .count()
    )
    user.is_connected = remaining_active > 0
    if target is not None:
        user.last_seen_at = ref_now
    db.commit()
    return target


def touch_user_activity(
    user: User,
    db: Session,
    jti: str | None = None,
    client_type: str = "web",
    ip_address: str | None = None,
    force: bool = False,
    now: datetime | None = None,
) -> Optional[UserSession]:
    """
    Actualiza `last_seen_at` y `UserSession.last_activity_at` de forma throttled.
    Si la sesión activa anterior ya expiró por inactividad, la cierra en su última actividad
    real y abre una nueva sesión desde `now` para no inflar horas inactivas.
    """
    ref_now = _as_utc(now) or datetime.now(timezone.utc)

    active: UserSession | None = None
    if jti:
        active = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user.id,
                UserSession.session_token_id == jti,
                UserSession.status == "active",
            )
            .order_by(UserSession.started_at.desc())
            .first()
        )
    if active is None:
        active = (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user.id,
                UserSession.status == "active",
            )
            .order_by(UserSession.started_at.desc())
            .first()
        )

    dirty = False

    if active is not None:
        last_act = _as_utc(active.last_activity_at) or _as_utc(active.started_at) or ref_now
        if (ref_now - last_act).total_seconds() > SESSION_TIMEOUT_SECONDS:
            # La sesión previa expiró por inactividad: cerrarla en su última actividad real
            started = _as_utc(active.started_at) or last_act
            active.ended_at = last_act
            active.duration_seconds = max(0, int((last_act - started).total_seconds()))
            active.status = "timeout"
            active.disconnect_reason = "inactivity_timeout"
            active = None
            dirty = True

    if active is None:
        # Crear sesión nueva (por ejemplo al retomar actividad tras timeout o token legado)
        active = UserSession(
            user_id=user.id,
            session_token_id=jti or uuid.uuid4().hex,
            client_type=client_type,
            ip_address=ip_address,
            started_at=ref_now,
            last_activity_at=ref_now,
            ended_at=None,
            duration_seconds=0,
            status="active",
            disconnect_reason=None,
        )
        db.add(active)
        user.is_connected = True
        user.last_seen_at = ref_now
        if user.last_login_at is None:
            user.last_login_at = ref_now
        dirty = True
    else:
        last_act = _as_utc(active.last_activity_at) or ref_now
        last_seen = _as_utc(getattr(user, "last_seen_at", None))
        need_update = (
            force
            or not getattr(user, "is_connected", False)
            or last_seen is None
            or (ref_now - last_act).total_seconds() >= TOUCH_THROTTLE_SECONDS
        )
        if need_update:
            started = _as_utc(active.started_at) or ref_now
            active.last_activity_at = ref_now
            active.duration_seconds = max(0, int((ref_now - started).total_seconds()))
            user.is_connected = True
            user.last_seen_at = ref_now
            dirty = True

    if dirty:
        db.commit()
    return active
