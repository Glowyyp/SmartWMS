"""
core/mfa.py — Autenticación multifactor basada en TOTP (RFC 6238)

Compatible con cualquier app autenticadora gratuita: Google Authenticator,
Microsoft Authenticator, Aegis, 2FAS, FreeOTP, Authy, etc.
No depende de servicios externos ni de conexión a Internet: el código de 6
dígitos se calcula localmente a partir de un secreto compartido y la hora.

Seguridad:
  • El secreto TOTP se almacena cifrado con Fernet (AES-128-CBC + HMAC-SHA256)
    usando MFA_ENCRYPTION_KEY (archivo .env, nunca en la base de datos).
  • Los códigos de recuperación se guardan solo como hash HMAC-SHA256 y son
    de un solo uso.
  • Protección contra reutilización: un mismo código TOTP no se acepta dos veces.
  • Bloqueo TEMPORAL tras varios intentos fallidos (no bloquea la cuenta para siempre).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken

from app.core.env import load_project_env, persist_env_value

load_project_env()
logger = logging.getLogger(__name__)

# ─── Parámetros (configurables desde .env) ────────────────────────────────────
MFA_ISSUER          = os.getenv("MFA_ISSUER", "SmartWMS")
MFA_MAX_ATTEMPTS    = int(os.getenv("MFA_MAX_ATTEMPTS", "5"))
MFA_LOCK_MINUTES    = int(os.getenv("MFA_LOCK_MINUTES", "5"))
MFA_VALID_WINDOW    = int(os.getenv("MFA_VALID_WINDOW", "1"))   # ±30 s de tolerancia de reloj
RECOVERY_CODE_COUNT = 10
TOTP_INTERVAL       = 30

# Roles a los que se exige MFA. "*" = todos los roles.
_REQUIRED_ROLES_RAW = os.getenv("MFA_REQUIRED_ROLES", "*").strip()

_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sin 0/O/1/I para evitar confusiones
_TOTP_RE = re.compile(r"^\d{6}$")


class MFAConfigError(RuntimeError):
    """La clave de cifrado MFA no está disponible o es inválida."""


def is_mfa_required_for_role(role: str | None) -> bool:
    if _REQUIRED_ROLES_RAW in ("*", "all", "todos"):
        return True
    if _REQUIRED_ROLES_RAW in ("", "none", "ninguno"):
        return False
    roles = {r.strip().lower() for r in _REQUIRED_ROLES_RAW.split(",") if r.strip()}
    return (role or "").lower() in roles


# ─── Clave de cifrado ─────────────────────────────────────────────────────────

_fernet: Fernet | None = None
_key_bytes: bytes | None = None


def _get_fernet() -> Fernet:
    """
    Obtiene el cifrador Fernet. Si MFA_ENCRYPTION_KEY no existe (PC nuevo),
    se genera una clave aleatoria y se guarda en el .env central para que
    sobreviva a reinicios. IMPORTANTE: si se pierde esta clave, los usuarios
    deberán volver a enrolar su autenticador (ver procedimiento de recuperación).
    """
    global _fernet, _key_bytes
    if _fernet is not None:
        return _fernet
    key = os.getenv("MFA_ENCRYPTION_KEY", "").strip()
    if not key:
        key = Fernet.generate_key().decode()
        if persist_env_value("MFA_ENCRYPTION_KEY", key):
            logger.warning("MFA_ENCRYPTION_KEY no existía: se generó una nueva y se guardó en .env")
        else:
            raise MFAConfigError(
                "Falta MFA_ENCRYPTION_KEY en .env y no se pudo generar automáticamente. "
                "Ejecuta instalar.bat o scripts\\setup_env.py."
            )
        os.environ["MFA_ENCRYPTION_KEY"] = key
    try:
        _fernet = Fernet(key.encode())
        _key_bytes = base64.urlsafe_b64decode(key.encode())
    except Exception as exc:  # clave mal formada
        raise MFAConfigError("MFA_ENCRYPTION_KEY inválida (debe ser una clave Fernet base64 de 32 bytes)") from exc
    return _fernet


def encrypt_secret(secret: str) -> str:
    return _get_fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.error("No se pudo descifrar un secreto MFA (¿cambió MFA_ENCRYPTION_KEY?)")
        return None


# ─── TOTP ─────────────────────────────────────────────────────────────────────

def generate_secret() -> str:
    """Secreto base32 de 160 bits (recomendación RFC 4226)."""
    return pyotp.random_base32(length=32)


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret, interval=TOTP_INTERVAL).provisioning_uri(name=email, issuer_name=MFA_ISSUER)


def qr_svg_data_uri(uri: str) -> str:
    """QR en SVG (data URI) generado localmente — no se envía a servicios externos."""
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#111111", light="#ffffff")


def verify_totp(secret: str, code: str, last_used_step: int | None) -> int | None:
    """
    Verifica un código TOTP con tolerancia de ±MFA_VALID_WINDOW intervalos.
    Devuelve el 'time step' aceptado (para guardarlo y evitar reutilización)
    o None si el código es inválido o ya fue usado.
    """
    code = (code or "").strip().replace(" ", "")
    if not _TOTP_RE.match(code):
        return None
    totp = pyotp.TOTP(secret, interval=TOTP_INTERVAL)
    current = int(time.time()) // TOTP_INTERVAL
    for offset in range(-MFA_VALID_WINDOW, MFA_VALID_WINDOW + 1):
        step = current + offset
        if hmac.compare_digest(totp.generate_otp(step), code):
            if last_used_step is not None and step <= last_used_step:
                return None   # código ya utilizado (ataque de repetición)
            return step
    return None


def looks_like_totp(code: str) -> bool:
    return bool(_TOTP_RE.match((code or "").strip().replace(" ", "")))


# ─── Códigos de recuperación ──────────────────────────────────────────────────

def _normalize_recovery(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _hash_recovery(code: str) -> str:
    _get_fernet()
    return hmac.new(_key_bytes or b"", _normalize_recovery(code).encode(), hashlib.sha256).hexdigest()


def generate_recovery_codes() -> tuple[list[str], str]:
    """Devuelve (códigos en claro para mostrar UNA vez, JSON de hashes para guardar)."""
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, json.dumps([_hash_recovery(c) for c in codes])


def consume_recovery_code(stored_json: str | None, code: str) -> str | None:
    """Si el código es válido lo elimina y devuelve el nuevo JSON; si no, None."""
    if not stored_json or len(_normalize_recovery(code)) != 10:
        return None
    try:
        hashes: list[str] = json.loads(stored_json)
    except (ValueError, TypeError):
        return None
    candidate = _hash_recovery(code)
    for h in hashes:
        if hmac.compare_digest(h, candidate):
            hashes.remove(h)
            return json.dumps(hashes)
    return None


def remaining_recovery_codes(stored_json: str | None) -> int:
    try:
        return len(json.loads(stored_json)) if stored_json else 0
    except (ValueError, TypeError):
        return 0


# ─── Bloqueo temporal por intentos fallidos ───────────────────────────────────

def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def lock_remaining_seconds(user) -> int:
    locked_until = _aware(user.mfa_locked_until)
    if not locked_until:
        return 0
    remaining = (locked_until - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(remaining))


def register_failure(user) -> None:
    user.mfa_failed_attempts = (user.mfa_failed_attempts or 0) + 1
    if user.mfa_failed_attempts >= MFA_MAX_ATTEMPTS:
        user.mfa_locked_until = datetime.now(timezone.utc) + timedelta(minutes=MFA_LOCK_MINUTES)
        user.mfa_failed_attempts = 0
        logger.warning("MFA bloqueado temporalmente (%s min) para %s", MFA_LOCK_MINUTES, user.email)


def register_success(user) -> None:
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None


def reset_user_mfa(user) -> None:
    """Desactiva MFA y borra secretos. El usuario deberá enrolarse en su próximo login."""
    user.mfa_enabled = False
    user.mfa_secret_enc = None
    user.mfa_pending_secret_enc = None
    user.mfa_recovery_codes = None
    user.mfa_last_used_step = None
    user.mfa_failed_attempts = 0
    user.mfa_locked_until = None
    user.mfa_enabled_at = None
