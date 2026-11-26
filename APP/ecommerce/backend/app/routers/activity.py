"""
routers/activity.py — Módulo de Registro de Actividad y Métricas de Usuarios (Supervisor/Admin)

Endpoints (todos restringidos a perfiles 'supervisor' y 'admin'):
  GET /api/v1/activity/overview          → KPIs generales, tabla de métricas por usuario, actividad diaria y feed reciente
  GET /api/v1/activity/users/{user_id}   → Detalle individual: métricas, gráfico diario e historial de conexiones
  GET /api/v1/activity/sessions          → Log histórico filtrable de conexiones

Reglas de seguridad y visibilidad:
  - Operarios reciben HTTP 403 Forbidden en todos los endpoints.
  - Supervisores solo pueden consultar usuarios con rol 'supervisor' u 'operario' (nunca 'admin'),
    y no se les exponen correos administrativos.
  - Administradores tienen visibilidad completa.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.presence import (
    SESSION_TIMEOUT_SECONDS,
    _as_utc,
    compute_session_duration_seconds,
    compute_user_online,
    is_session_effectively_online,
    reconcile_stale_sessions,
)
from app.database import get_db
from app.models.user import User
from app.models.user_session import UserSession
from app.routers.auth import require_supervisor_or_admin

router = APIRouter(prefix="/api/v1/activity", tags=["Actividad y Métricas de Usuarios"])


# ─── Schemas de Respuesta ─────────────────────────────────────────────────────

class SessionLogOut(BaseModel):
    id: int
    user_id: int
    user_name: str
    role: str
    client_type: str
    started_at: datetime
    last_activity_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: int
    status: str  # 'active' | 'closed' | 'timeout'
    disconnect_reason: Optional[str] = None
    is_online: bool


class DailyActivityPoint(BaseModel):
    date: str                 # YYYY-MM-DD
    label: str                # DD/MM
    duration_seconds: int
    sessions_count: int
    active_users_count: int = 0


class UserActivitySummaryOut(BaseModel):
    user_id: int
    user_name: str
    full_name: Optional[str] = None
    email: Optional[str] = None  # Solo visible para admin
    role: str
    is_active: bool
    is_online: bool
    total_sessions: int
    total_duration_seconds: int
    avg_session_seconds: int
    today_duration_seconds: int
    week_duration_seconds: int
    sessions_last_7_days: int
    sessions_last_30_days: int
    active_days_last_30_days: int
    avg_sessions_per_active_day: float
    frequency_label: str
    last_login_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    last_client_type: Optional[str] = None


class ActivityOverviewSummary(BaseModel):
    total_users: int
    online_users: int
    offline_users: int
    active_sessions_count: int
    total_sessions_count: int
    total_usage_seconds: int
    period_usage_seconds: int
    session_timeout_seconds: int


class ActivityOverviewOut(BaseModel):
    summary: ActivityOverviewSummary
    users: List[UserActivitySummaryOut]
    daily_activity: List[DailyActivityPoint]
    recent_activity: List[SessionLogOut]


class UserActivityDetailOut(BaseModel):
    user: UserActivitySummaryOut
    daily_activity: List[DailyActivityPoint]
    sessions: List[SessionLogOut]


# ─── Helpers de cálculo y aislamiento por rol ────────────────────────────────

def _display_name(user: User) -> str:
    return (user.full_name or "").strip() or user.email.split("@")[0]


def _visible_users(db: Session, viewer: User) -> list[User]:
    q = db.query(User)
    if viewer.role != "admin":
        q = q.filter(User.role.in_(["supervisor", "operario"]))
    return q.order_by(User.full_name.asc(), User.email.asc()).all()


def _overlap_seconds(
    start: datetime,
    end: datetime,
    window_start: datetime,
    window_end: datetime,
) -> int:
    s = max(start, window_start)
    e = min(end, window_end)
    if e <= s:
        return 0
    return int((e - s).total_seconds())


def _effective_session_bounds(
    sess: UserSession,
    now: datetime,
) -> tuple[datetime, datetime, int]:
    started = _as_utc(sess.started_at) or now
    duration = compute_session_duration_seconds(sess, now=now)
    if sess.ended_at is not None:
        ended = _as_utc(sess.ended_at) or started
    else:
        ended = started + timedelta(seconds=duration)
    if ended < started:
        ended = started
    return started, ended, duration


def _frequency_label(sessions_7d: int, active_days_30d: int) -> str:
    if sessions_7d == 0 and active_days_30d == 0:
        return "Sin actividad reciente"
    if sessions_7d >= 10:
        return f"Muy alta ({sessions_7d} ses./sem)"
    if sessions_7d >= 5:
        return f"Alta ({sessions_7d} ses./sem)"
    if sessions_7d >= 2:
        return f"Moderada ({sessions_7d} ses./sem)"
    if sessions_7d == 1:
        return "Baja (1 ses./sem)"
    return f"Esporádica ({active_days_30d} día(s)/30d)"


def _serialize_session(sess: UserSession, user: User, now: datetime) -> SessionLogOut:
    online = is_session_effectively_online(sess, now=now)
    duration = compute_session_duration_seconds(sess, now=now)
    return SessionLogOut(
        id=sess.id,
        user_id=user.id,
        user_name=_display_name(user),
        role=user.role,
        client_type=sess.client_type or "web",
        started_at=_as_utc(sess.started_at) or now,
        last_activity_at=_as_utc(sess.last_activity_at) or _as_utc(sess.started_at) or now,
        ended_at=_as_utc(sess.ended_at),
        duration_seconds=duration,
        status="active" if online else (sess.status if sess.status != "active" else "timeout"),
        disconnect_reason=sess.disconnect_reason,
        is_online=online,
    )


def _compute_user_summary(
    user: User,
    sessions: list[UserSession],
    viewer_role: str,
    now: datetime,
) -> UserActivitySummaryOut:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now - timedelta(days=30)

    total_duration = 0
    today_duration = 0
    week_duration = 0
    sessions_7d = 0
    sessions_30d = 0
    active_days_30d: set[str] = set()
    has_online_session = False

    last_login: datetime | None = _as_utc(user.last_login_at)
    last_activity: datetime | None = _as_utc(user.last_seen_at)
    last_client_type: str | None = None

    for sess in sessions:
        started, ended, duration = _effective_session_bounds(sess, now)
        total_duration += duration
        today_duration += _overlap_seconds(started, ended, today_start, now)
        week_duration += _overlap_seconds(started, ended, week_start, now)

        if started >= week_start or ended >= week_start:
            sessions_7d += 1
        if started >= month_start or ended >= month_start:
            sessions_30d += 1
            # Contabilizar cada día UTC en el que esta sesión estuvo activa en los últimos 30 días
            day_cursor = max(started, month_start).date()
            end_day = min(ended, now).date()
            while day_cursor <= end_day:
                active_days_30d.add(day_cursor.isoformat())
                day_cursor += timedelta(days=1)

        if is_session_effectively_online(sess, now=now):
            has_online_session = True

        if last_login is None or started > last_login:
            last_login = started
            last_client_type = sess.client_type or "web"
        elif last_client_type is None:
            last_client_type = sess.client_type or "web"

        sess_act = _as_utc(sess.last_activity_at) or ended
        if last_activity is None or sess_act > last_activity:
            last_activity = sess_act

    total_sessions = len(sessions)
    avg_session = int(round(total_duration / total_sessions)) if total_sessions > 0 else 0
    active_days_count = len(active_days_30d)
    avg_per_active_day = round(sessions_30d / active_days_count, 2) if active_days_count > 0 else 0.0
    is_online = has_online_session or compute_user_online(user, now=now)

    return UserActivitySummaryOut(
        user_id=user.id,
        user_name=_display_name(user),
        full_name=user.full_name,
        email=user.email if viewer_role == "admin" else None,
        role=user.role,
        is_active=user.is_active,
        is_online=is_online,
        total_sessions=total_sessions,
        total_duration_seconds=total_duration,
        avg_session_seconds=avg_session,
        today_duration_seconds=today_duration,
        week_duration_seconds=week_duration,
        sessions_last_7_days=sessions_7d,
        sessions_last_30_days=sessions_30d,
        active_days_last_30_days=active_days_count,
        avg_sessions_per_active_day=avg_per_active_day,
        frequency_label=_frequency_label(sessions_7d, active_days_count),
        last_login_at=last_login,
        last_activity_at=last_activity,
        last_client_type=last_client_type,
    )


def _build_daily_series(
    sessions: list[UserSession],
    days: int,
    now: datetime,
) -> list[DailyActivityPoint]:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    points: list[DailyActivityPoint] = []

    for offset in range(days - 1, -1, -1):
        day_start = today_start - timedelta(days=offset)
        day_end = min(day_start + timedelta(days=1), now) if offset == 0 else day_start + timedelta(days=1)

        day_duration = 0
        day_sessions = 0
        day_users: set[int] = set()

        for sess in sessions:
            started, ended, _ = _effective_session_bounds(sess, now)
            overlap = _overlap_seconds(started, ended, day_start, day_end)
            started_this_day = day_start <= started < (day_start + timedelta(days=1))
            if overlap > 0 or started_this_day:
                day_duration += overlap
                if started_this_day:
                    day_sessions += 1
                day_users.add(sess.user_id)

        points.append(
            DailyActivityPoint(
                date=day_start.date().isoformat(),
                label=day_start.strftime("%d/%m"),
                duration_seconds=day_duration,
                sessions_count=day_sessions,
                active_users_count=len(day_users),
            )
        )
    return points


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "/overview",
    response_model=ActivityOverviewOut,
    summary="Vista general de actividad y métricas de usuarios (Supervisor/Admin)",
)
def get_activity_overview(
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    now = datetime.now(timezone.utc)
    reconcile_stale_sessions(db, now=now)

    users = _visible_users(db, current_user)
    user_by_id = {u.id: u for u in users}
    visible_ids = list(user_by_id.keys())

    sessions: list[UserSession] = []
    if visible_ids:
        sessions = (
            db.query(UserSession)
            .filter(UserSession.user_id.in_(visible_ids))
            .order_by(UserSession.started_at.desc())
            .all()
        )

    sessions_by_user: dict[int, list[UserSession]] = defaultdict(list)
    for sess in sessions:
        sessions_by_user[sess.user_id].append(sess)

    user_summaries = [
        _compute_user_summary(u, sessions_by_user.get(u.id, []), current_user.role, now)
        for u in users
    ]
    # Conectados primero, luego mayor tiempo total de uso
    user_summaries.sort(key=lambda u: (not u.is_online, -u.total_duration_seconds, u.user_name.lower()))

    daily_activity = _build_daily_series(sessions, days=days, now=now)
    period_usage = sum(pt.duration_seconds for pt in daily_activity)

    online_users = sum(1 for u in user_summaries if u.is_online)
    total_users = len(user_summaries)
    active_sessions_count = sum(1 for s in sessions if is_session_effectively_online(s, now=now))
    total_usage_seconds = sum(u.total_duration_seconds for u in user_summaries)

    recent = [
        _serialize_session(s, user_by_id[s.user_id], now)
        for s in sessions[:25]
        if s.user_id in user_by_id
    ]

    return ActivityOverviewOut(
        summary=ActivityOverviewSummary(
            total_users=total_users,
            online_users=online_users,
            offline_users=max(0, total_users - online_users),
            active_sessions_count=active_sessions_count,
            total_sessions_count=len(sessions),
            total_usage_seconds=total_usage_seconds,
            period_usage_seconds=period_usage,
            session_timeout_seconds=SESSION_TIMEOUT_SECONDS,
        ),
        users=user_summaries,
        daily_activity=daily_activity,
        recent_activity=recent,
    )


@router.get(
    "/users/{user_id}",
    response_model=UserActivityDetailOut,
    summary="Historial de conexiones y métricas individuales de un usuario (Supervisor/Admin)",
)
def get_user_activity_detail(
    user_id: int,
    days: int = Query(default=14, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    now = datetime.now(timezone.utc)
    reconcile_stale_sessions(db, user_id=user_id, now=now)

    q = db.query(User).filter(User.id == user_id)
    if current_user.role != "admin":
        q = q.filter(User.role.in_(["supervisor", "operario"]))
    user = q.first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con id={user_id} no encontrado o sin permisos para consultarlo",
        )

    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id)
        .order_by(UserSession.started_at.desc())
        .all()
    )

    summary = _compute_user_summary(user, sessions, current_user.role, now)
    daily_activity = _build_daily_series(sessions, days=days, now=now)
    serialized_sessions = [_serialize_session(s, user, now) for s in sessions[:limit]]

    return UserActivityDetailOut(
        user=summary,
        daily_activity=daily_activity,
        sessions=serialized_sessions,
    )


@router.get(
    "/sessions",
    response_model=List[SessionLogOut],
    summary="Listar log histórico de sesiones (Supervisor/Admin)",
)
def list_activity_sessions(
    user_id: Optional[int] = Query(default=None),
    session_status: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    now = datetime.now(timezone.utc)
    reconcile_stale_sessions(db, user_id=user_id, now=now)

    users = _visible_users(db, current_user)
    user_by_id = {u.id: u for u in users}
    if user_id is not None and user_id not in user_by_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con id={user_id} no encontrado o sin permisos",
        )

    target_ids = [user_id] if user_id is not None else list(user_by_id.keys())
    if not target_ids:
        return []

    q = db.query(UserSession).filter(UserSession.user_id.in_(target_ids))
    if session_status:
        q = q.filter(UserSession.status == session_status.strip().lower())

    rows = q.order_by(UserSession.started_at.desc()).limit(limit).all()
    return [_serialize_session(s, user_by_id[s.user_id], now) for s in rows if s.user_id in user_by_id]
