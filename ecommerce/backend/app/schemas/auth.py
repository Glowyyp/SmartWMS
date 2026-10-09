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
    """Token JWT devuelto tras un login/registro exitoso.
    El campo `role` es requerido por el auth.service.ts y role.guard.ts de Angular.
    """
    access_token: str
    token_type: str = "bearer"
    role: str  # Retornado explícitamente para Angular


class UserOut(BaseModel):
    """Representación pública del usuario (sin datos sensibles)."""
    id: int
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
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
    created_at: datetime
    hashed_password: str  # hash bcrypt — visible solo para admin/dev

    model_config = {"from_attributes": True}
