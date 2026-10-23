"""
core/security.py — Utilidades de seguridad: hashing bcrypt + JWT

Centraliza toda la lógica criptográfica para que sea fácil de cambiar
(p.ej., migrar de HS256 a RS256 en producción).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.env import load_project_env

load_project_env()

# ─── Configuración ────────────────────────────────────────────────────────────
JWT_SECRET      = os.getenv("JWT_SECRET", "cambia_este_secreto_jwt_en_produccion")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_MIN  = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

# Tipos de token: solo TOKEN_TYPE_ACCESS da acceso a la API.
# TOKEN_TYPE_MFA_PENDING se emite tras validar la contraseña y SOLO sirve para
# completar el segundo factor (endpoints /api/auth/mfa/*).
TOKEN_TYPE_ACCESS      = "access"
TOKEN_TYPE_MFA_PENDING = "mfa_pending"
MFA_TOKEN_EXPIRE_MIN   = int(os.getenv("MFA_TOKEN_EXPIRE_MINUTES", "5"))

# Contexto bcrypt para hashing de contraseñas
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Contraseñas ──────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Devuelve el hash bcrypt de la contraseña en texto plano (corte seguro a 72 bytes)."""
    safe = plain.encode("utf-8")[:72].decode("utf-8", "ignore")
    return _pwd_ctx.hash(safe)


def verify_password(plain: str, hashed: str) -> bool:
    """Compara una contraseña en texto plano contra su hash bcrypt (corte seguro a 72 bytes)."""
    safe = plain.encode("utf-8")[:72].decode("utf-8", "ignore")
    return _pwd_ctx.verify(safe, hashed)


# ─── JWT ──────────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Genera un JWT firmado con HS256.

    :param data:          payload a incluir (e.g. {"sub": email, "role": "admin"})
    :param expires_delta: duración del token (default: JWT_EXPIRE_MIN minutos)
    """
    payload = data.copy()
    payload.setdefault("typ", TOKEN_TYPE_ACCESS)
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MIN))
    payload.update({"exp": expire})
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_mfa_pending_token(email: str, stage: str) -> str:
    """
    Token de corta duración que acredita SOLO el primer factor (contraseña).
    stage: 'verify' (usuario ya enrolado) | 'setup' (debe vincular su autenticador).
    No incluye el rol y es rechazado por get_current_user y por el Bot.
    """
    return create_access_token(
        {"sub": email, "typ": TOKEN_TYPE_MFA_PENDING, "stage": stage},
        expires_delta=timedelta(minutes=MFA_TOKEN_EXPIRE_MIN),
    )


def decode_access_token(token: str) -> dict:
    """
    Decodifica y valida un JWT.

    :raises JWTError: si el token es inválido, expirado o manipulado.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
