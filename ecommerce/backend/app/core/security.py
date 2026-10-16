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

# ─── Configuración ────────────────────────────────────────────────────────────
JWT_SECRET      = os.getenv("JWT_SECRET", "cambia_este_secreto_jwt_en_produccion")
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_MIN  = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

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
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRE_MIN))
    payload.update({"exp": expire})
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decodifica y valida un JWT.

    :raises JWTError: si el token es inválido, expirado o manipulado.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
