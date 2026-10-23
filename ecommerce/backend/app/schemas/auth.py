"""
schemas/auth.py — Pydantic schemas para Autenticación de Usuarios

Roles unificados en todo el sistema: "admin" | "supervisor" | "operario"
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


# ─── Registro ─────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    """Payload para registrar un nuevo usuario."""
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    role: Literal["admin", "supervisor", "operario"] = "operario"


# ─── Login ────────────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    """Credenciales para iniciar sesión."""
    email: EmailStr
    password: str


# ─── Respuestas ───────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    """Respuesta del endpoint de login.
    Si mfa_required es False, access_token contiene el JWT final listo para usar.
    Si mfa_required es True, access_token está vacío o no se entrega, y en su lugar
    se entrega mfa_token (de validez corta) y stage ('verify' o 'setup').
    """
    access_token: str | None = None
    token_type: str = "bearer"
    role: str
    mfa_required: bool = False
    mfa_token: str | None = None
    stage: str | None = None  # "verify" | "setup" | None


# ─── Schemas MFA ─────────────────────────────────────────────────────────────

class MFASetupResponse(BaseModel):
    """Datos para vincular la aplicación TOTP (Google Authenticator, Microsoft, Aegis)."""
    secret: str                      # Clave secreta en base32 (para ingreso manual)
    provisioning_uri: str            # otpauth:// URI estándar RFC 6238
    qr_code_svg: str                 # Data URI en formato SVG para renderizar el QR localmente
    recovery_codes: list[str]        # 10 códigos de un solo uso para emergencias
    issuer: str
    account_name: str


class MFAActivateRequest(BaseModel):
    """Confirmación del primer código TOTP para activar MFA definitivamente."""
    code: str = Field(min_length=6, max_length=6, description="Código de 6 dígitos generado por la app")
    mfa_token: str | None = None      # Opcional si se envía como Bearer header


class MFAVerifyRequest(BaseModel):
    """Verificación del segundo factor en login."""
    code: str = Field(min_length=6, max_length=6, description="Código de 6 dígitos de la app autenticadora")
    mfa_token: str | None = None      # Opcional si se envía como Bearer header


class MFARecoverRequest(BaseModel):
    """Recuperación de acceso usando un código de emergencia de un solo uso."""
    recovery_code: str = Field(min_length=10, max_length=12, description="Código de recuperación (ej: ABCDE-12345)")
    mfa_token: str | None = None


class MFAStatusResponse(BaseModel):
    """Estado de MFA del usuario actual."""
    mfa_enabled: bool
    remaining_recovery_codes: int
    enabled_at: datetime | None = None


class UserOut(BaseModel):
    """Representación pública del usuario (sin datos sensibles)."""
    id: int
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
    mfa_enabled: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserOut(BaseModel):
    """Representación completa del usuario para administración/desarrollo.
    Incluye hashed_password para verificación. Solo accessible por admins.
    """
    id: int
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
    mfa_enabled: bool = False
    created_at: datetime
    hashed_password: str  # hash bcrypt — visible solo para admin/dev

    model_config = {"from_attributes": True}

