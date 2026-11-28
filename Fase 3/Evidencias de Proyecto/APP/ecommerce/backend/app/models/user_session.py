"""
models/user_session.py — Registro histórico de sesiones y conexiones de usuarios.

Registra cada inicio de sesión, última actividad, cierre explícito o cierre automático
por inactividad/desconexión inesperada, junto con la duración consolidada en segundos.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.database import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Identificador único del token JWT (claim 'jti') asociado a esta sesión
    session_token_id = Column(String(64), nullable=True, index=True)

    # Origen del cliente: 'web' | 'mobile' | 'api'
    client_type = Column(String(32), nullable=False, default="web")
    ip_address = Column(String(64), nullable=True)

    # Tiempos de sesión
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # Duración consolidada en segundos
    duration_seconds = Column(Integer, nullable=False, default=0)

    # Estado: 'active' | 'closed' | 'timeout'
    status = Column(String(20), nullable=False, default="active", index=True)
    # Motivo de cierre: 'logout' | 'inactivity_timeout' | 'new_login' | None
    disconnect_reason = Column(String(50), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<UserSession id={self.id} user_id={self.user_id} "
            f"status={self.status} duration={self.duration_seconds}s>"
        )
