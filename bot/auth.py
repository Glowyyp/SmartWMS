"""
bot/auth.py — Utilidades de autenticación del Bot (puerto 8000)

Usa el mismo JWT_SECRET que el backend (puerto 8001) para validar
los tokens emitidos por /api/auth/login. El bot no emite tokens propios.
"""

import os
from datetime import datetime, timedelta

import bcrypt

# Parche de compatibilidad para passlib con bcrypt >= 4.0
if not hasattr(bcrypt, "__about__"):
    class About:
        __version__ = getattr(bcrypt, "__version__", "4.0.0")
    bcrypt.__about__ = About

from passlib.context import CryptContext
from jose import JWTError, jwt

# Compartir el mismo secreto que el backend — cargado desde .env
JWT_SECRET    = os.getenv("JWT_SECRET", "cambia_este_secreto_jwt_en_produccion")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Contraseñas ─────────────────────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    safe = plain_password.encode("utf-8")[:72].decode("utf-8", "ignore")
    return pwd_context.verify(safe, hashed_password)


def get_password_hash(password: str) -> str:
    safe = password.encode("utf-8")[:72].decode("utf-8", "ignore")
    return pwd_context.hash(safe)


# ─── JWT ─────────────────────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Genera un JWT firmado con el mismo secret que el backend."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decodifica y valida un JWT emitido por el backend.
    :raises JWTError: si el token es inválido, expirado o no coincide el secret.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
