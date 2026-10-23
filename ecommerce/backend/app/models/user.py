"""
models/user.py — Modelo ORM para la tabla de Usuarios

Roles unificados en todo el sistema: 'admin' | 'supervisor' | 'operario'.
Las contraseñas se almacenan como hash bcrypt (nunca en texto plano).
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String(254), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name      = Column(String(200), nullable=True)
    role           = Column(String(50),  nullable=False, default="operario")
    # roles posibles: 'admin' | 'supervisor' | 'operario'

    is_active      = Column(Boolean, default=True, nullable=False)

    # ─── Autenticación multifactor (TOTP RFC 6238) ───────────────────────────
    # Los secretos se guardan CIFRADOS (Fernet/AES) y los códigos de recuperación
    # solo como hash HMAC-SHA256; nunca se devuelven en respuestas de la API.
    mfa_enabled            = Column(Boolean, default=False, nullable=False)
    mfa_secret_enc         = Column(Text, nullable=True)     # secreto TOTP activo (cifrado)
    mfa_pending_secret_enc = Column(Text, nullable=True)     # secreto en proceso de enrolamiento
    mfa_recovery_codes     = Column(Text, nullable=True)     # JSON con hashes de códigos de un solo uso
    mfa_last_used_step     = Column(Integer, nullable=True)  # anti-reutilización de códigos TOTP
    mfa_failed_attempts    = Column(Integer, default=0, nullable=False)
    mfa_locked_until       = Column(DateTime(timezone=True), nullable=True)  # bloqueo temporal
    mfa_enabled_at         = Column(DateTime(timezone=True), nullable=True)


    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(),
                            onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
