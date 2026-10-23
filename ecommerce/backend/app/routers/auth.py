"""
routers/auth.py — Endpoints de Autenticación con soporte completo para MFA (TOTP)

Flujo de Autenticación Multifactor:
  1. POST /api/auth/login:
     - Valida email y contraseña.
     - Si el usuario tiene MFA activado o requerido por política, devuelve un
       mfa_token temporal de 5 minutos (tipo 'mfa_pending') y stage ('verify' o 'setup').
     - NO entrega access_token hasta que el segundo factor sea validado con éxito.
  2. POST /api/auth/mfa/setup:
     - Genera secreto TOTP cifrado (Fernet) y códigos de recuperación de emergencia.
     - Devuelve el secreto en texto plano, URI otpauth://, QR en formato SVG y los códigos.
  3. POST /api/auth/mfa/activate:
     - Verifica el primer código TOTP contra el secreto en enrolamiento.
     - Al validar, activa MFA definitivamente y entrega el JWT access_token final.
  4. POST /api/auth/mfa/verify:
     - Verifica el código de 6 dígitos con protección contra reutilización (replay attack)
       y bloqueo temporal tras 5 intentos fallidos consecutivos.
     - Entrega el JWT access_token final con el rol correspondiente.
  5. POST /api/auth/mfa/recover:
     - Permite acceder usando uno de los 10 códigos de recuperación de un solo uso.
  6. GET /api/auth/mfa/status:
     - Consulta el estado actual de MFA del usuario autenticado.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.orm import Session

from app.core import mfa
from app.core.security import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_MFA_PENDING,
    create_access_token,
    create_mfa_pending_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    MFAActivateRequest,
    MFARecoverRequest,
    MFASetupResponse,
    MFAStatusResponse,
    MFAVerifyRequest,
    TokenResponse,
    UserCreate,
    UserOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

# Extrae el token del header Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ─── Dependencias de Autenticación ────────────────────────────────────────────

def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependencia estándar para endpoints protegidos de la API.
    Exige un token JWT válido de tipo 'access'.
    Rechaza terminantemente tokens parciales 'mfa_pending' (HTTP 401).
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales de acceso inválidas o sesión expirada",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc

    try:
        payload = decode_access_token(token)
        token_type = payload.get("typ", TOKEN_TYPE_ACCESS)
        if token_type != TOKEN_TYPE_ACCESS:
            # Sesión incompleta: el segundo factor no ha sido verificado
            raise credentials_exc

        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active:
        raise credentials_exc
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependencia que exige rol 'admin'."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren privilegios de administrador",
        )
    return current_user


def require_supervisor_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependencia que permite acceso a supervisor y admin."""
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren privilegios de supervisor o administrador",
        )
    return current_user


def _resolve_mfa_user(
    token_candidate: str | None,
    authorization_header: str | None,
    db: Session,
    allowed_types: tuple[str, ...] = (TOKEN_TYPE_MFA_PENDING,),
) -> tuple[User, dict]:
    """
    Resuelve el usuario a partir del token MFA enviado en el body o en Authorization header.
    Comprueba existencia, activación y bloqueo temporal por intentos fallidos.
    """
    raw_token = token_candidate
    if not raw_token and authorization_header and authorization_header.startswith("Bearer "):
        raw_token = authorization_header[7:].strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere token de autenticación (mfa_token o Bearer)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(raw_token)
        typ = payload.get("typ")
        if typ not in allowed_types:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tipo de token no válido para esta operación",
            )
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token no contiene identidad de usuario",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token MFA inválido o expirado. Inicia sesión nuevamente.",
        )

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o cuenta inactiva",
        )

    lock_secs = mfa.lock_remaining_seconds(user)
    if lock_secs > 0:
        mins = (lock_secs // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Cuenta bloqueada temporalmente por intentos fallidos. Intenta nuevamente en {mins} minuto(s).",
        )

    return user, payload


# ─── Endpoints de Autenticación ───────────────────────────────────────────────

@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Crea un nuevo usuario en el sistema.
    Roles admitidos: 'admin', 'supervisor', 'operario'.
    """
    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un usuario con el email '{user_in.email}'",
        )

    user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        mfa_enabled=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Usuario registrado: %s (rol: %s)", user.email, user.role)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login y evaluación de segundo factor",
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Paso 1 del inicio de sesión: valida usuario y contraseña.
    - Si el usuario tiene MFA activado: emite token temporal 'mfa_pending' (stage='verify').
    - Si la política de seguridad exige MFA y el usuario no se ha enrolado: emite
      token temporal 'mfa_pending' (stage='setup') para obligar al enrolamiento inicial.
    - Si MFA no es requerido ni está activado: emite el JWT 'access_token' final directamente.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cuenta desactivada. Contacta al administrador.",
        )

    # Verificar bloqueo temporal por intentos fallidos de MFA previos
    lock_secs = mfa.lock_remaining_seconds(user)
    if lock_secs > 0:
        mins = (lock_secs // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Cuenta bloqueada temporalmente por intentos fallidos. Intenta nuevamente en {mins} minuto(s).",
        )

    # Caso 1: MFA ya está activo en la cuenta
    if user.mfa_enabled:
        pending_token = create_mfa_pending_token(user.email, stage="verify")
        logger.info("Login paso 1 OK para %s (%s). Requerido TOTP (verify).", user.email, user.role)
        return TokenResponse(
            access_token=None,
            role=user.role,
            mfa_required=True,
            mfa_token=pending_token,
            stage="verify",
        )

    # Caso 2: Política de seguridad exige MFA para este rol y aún no se ha enrolado
    if mfa.is_mfa_required_for_role(user.role):
        pending_token = create_mfa_pending_token(user.email, stage="setup")
        logger.info("Login paso 1 OK para %s (%s). Requerido enrolamiento inicial MFA (setup).", user.email, user.role)
        return TokenResponse(
            access_token=None,
            role=user.role,
            mfa_required=True,
            mfa_token=pending_token,
            stage="setup",
        )

    # Caso 3: MFA no requerido por política (compatibilidad hacia atrás)
    final_token = create_access_token({"sub": user.email, "role": user.role})
    logger.info("Login completo directo (sin MFA) para %s (%s)", user.email, user.role)
    return TokenResponse(
        access_token=final_token,
        role=user.role,
        mfa_required=False,
    )


# ─── Endpoints MFA ────────────────────────────────────────────────────────────

@router.post(
    "/mfa/setup",
    response_model=MFASetupResponse,
    summary="Generar secreto TOTP y códigos de recuperación",
)
def mfa_setup(
    authorization: str | None = Header(default=None),
    body_token: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Inicia el enrolamiento MFA.
    Permite ser llamado tanto con token 'mfa_pending' (en el login) como con
    'access_token' (usuario autenticado que desea vincular o reconfigurar su app).
    Genera un secreto TOTP cifrado y 10 códigos de recuperación únicos.
    """
    user, _ = _resolve_mfa_user(
        token_candidate=body_token,
        authorization_header=authorization,
        db=db,
        allowed_types=(TOKEN_TYPE_MFA_PENDING, TOKEN_TYPE_ACCESS),
    )

    plain_secret = mfa.generate_secret()
    enc_secret = mfa.encrypt_secret(plain_secret)

    plain_codes, recovery_json = mfa.generate_recovery_codes()

    # Guardar en estado pendiente (no activa MFA hasta validar el primer código)
    user.mfa_pending_secret_enc = enc_secret
    user.mfa_recovery_codes = recovery_json
    db.commit()

    uri = mfa.provisioning_uri(plain_secret, user.email)
    qr_svg = mfa.qr_svg_data_uri(uri)

    logger.info("Enrolamiento MFA iniciado para %s", user.email)
    return MFASetupResponse(
        secret=plain_secret,
        provisioning_uri=uri,
        qr_code_svg=qr_svg,
        recovery_codes=plain_codes,
        issuer=mfa.MFA_ISSUER,
        account_name=user.email,
    )


@router.post(
    "/mfa/activate",
    response_model=TokenResponse,
    summary="Confirmar código TOTP y activar MFA en la cuenta",
)
def mfa_activate(
    payload: MFAActivateRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Valida el primer código de 6 dígitos generado por la app autenticadora.
    Si coincide, promueve el secreto pendiente a definitivo, activa mfa_enabled=True,
    y emite el JWT access_token final.
    """
    user, _ = _resolve_mfa_user(
        token_candidate=payload.mfa_token,
        authorization_header=authorization,
        db=db,
        allowed_types=(TOKEN_TYPE_MFA_PENDING, TOKEN_TYPE_ACCESS),
    )

    if not user.mfa_pending_secret_enc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay un proceso de vinculación MFA pendiente. Llama primero a /api/auth/mfa/setup.",
        )

    secret = mfa.decrypt_secret(user.mfa_pending_secret_enc)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar la clave de autenticación en el servidor",
        )

    accepted_step = mfa.verify_totp(secret, payload.code, last_used_step=None)
    if accepted_step is None:
        mfa.register_failure(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Código incorrecto o expirado. Verifica la hora de tu dispositivo e inténtalo de nuevo.",
        )

    # Activación exitosa
    user.mfa_secret_enc = user.mfa_pending_secret_enc
    user.mfa_pending_secret_enc = None
    user.mfa_enabled = True
    user.mfa_enabled_at = datetime.now(timezone.utc)
    user.mfa_last_used_step = accepted_step
    mfa.register_success(user)
    db.commit()

    logger.info("MFA activado con éxito para %s (rol: %s)", user.email, user.role)
    access_token = create_access_token({"sub": user.email, "role": user.role})
    return TokenResponse(
        access_token=access_token,
        role=user.role,
        mfa_required=False,
    )


@router.post(
    "/mfa/verify",
    response_model=TokenResponse,
    summary="Verificar código TOTP de segundo factor",
)
def mfa_verify(
    payload: MFAVerifyRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Paso 2 del login con MFA: verifica el código de 6 dígitos de la app autenticadora.
    - Rechaza códigos reutilizados en la misma ventana de tiempo (replay attack).
    - Registra intentos fallidos y bloquea temporalmente tras alcanzar el límite.
    - Devuelve el access_token definitivo con el rol del usuario.
    """
    user, _ = _resolve_mfa_user(
        token_candidate=payload.mfa_token,
        authorization_header=authorization,
        db=db,
        allowed_types=(TOKEN_TYPE_MFA_PENDING,),
    )

    if not user.mfa_enabled or not user.mfa_secret_enc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El usuario no tiene MFA configurado. Ejecuta el enrolamiento inicial.",
        )

    secret = mfa.decrypt_secret(user.mfa_secret_enc)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al procesar el secreto MFA en el servidor",
        )

    accepted_step = mfa.verify_totp(secret, payload.code, last_used_step=user.mfa_last_used_step)
    if accepted_step is None:
        mfa.register_failure(user)
        db.commit()

        lock_secs = mfa.lock_remaining_seconds(user)
        if lock_secs > 0:
            mins = (lock_secs // 60) + 1
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Demasiados intentos fallidos. Cuenta bloqueada temporalmente por {mins} minuto(s).",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código de autenticación incorrecto o expirado.",
        )

    # Éxito: registrar paso y limpiar intentos fallidos
    user.mfa_last_used_step = accepted_step
    mfa.register_success(user)
    db.commit()

    logger.info("Segundo factor validado con éxito para %s (%s)", user.email, user.role)
    access_token = create_access_token({"sub": user.email, "role": user.role})
    return TokenResponse(
        access_token=access_token,
        role=user.role,
        mfa_required=False,
    )


@router.post(
    "/mfa/recover",
    response_model=TokenResponse,
    summary="Acceso de emergencia usando código de recuperación",
)
def mfa_recover(
    payload: MFARecoverRequest,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """
    Permite acceder si el usuario extravió su app autenticadora, utilizando uno
    de los 10 códigos de recuperación generados durante el enrolamiento.
    Cada código es de un solo uso y se elimina inmediatamente al ser consumido.
    """
    user, _ = _resolve_mfa_user(
        token_candidate=payload.mfa_token,
        authorization_header=authorization,
        db=db,
        allowed_types=(TOKEN_TYPE_MFA_PENDING,),
    )

    if not user.mfa_enabled or not user.mfa_recovery_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No hay códigos de recuperación configurados para esta cuenta.",
        )

    new_codes_json = mfa.consume_recovery_code(user.mfa_recovery_codes, payload.recovery_code)
    if new_codes_json is None:
        mfa.register_failure(user)
        db.commit()

        lock_secs = mfa.lock_remaining_seconds(user)
        if lock_secs > 0:
            mins = (lock_secs // 60) + 1
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Demasiados intentos fallidos. Cuenta bloqueada temporalmente por {mins} minuto(s).",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Código de recuperación no válido o ya utilizado.",
        )

    user.mfa_recovery_codes = new_codes_json
    mfa.register_success(user)
    db.commit()

    remaining = mfa.remaining_recovery_codes(new_codes_json)
    logger.warning("Usuario %s accedió con código de recuperación. Códigos restantes: %d", user.email, remaining)

    access_token = create_access_token({"sub": user.email, "role": user.role})
    return TokenResponse(
        access_token=access_token,
        role=user.role,
        mfa_required=False,
    )


@router.get(
    "/mfa/status",
    response_model=MFAStatusResponse,
    summary="Estado de MFA del usuario autenticado",
)
def mfa_status(current_user: User = Depends(get_current_user)):
    """Informa si MFA está activo, la fecha de activación y cuántos códigos restan."""
    remaining = mfa.remaining_recovery_codes(current_user.mfa_recovery_codes)
    return MFAStatusResponse(
        mfa_enabled=bool(current_user.mfa_enabled),
        remaining_recovery_codes=remaining,
        enabled_at=current_user.mfa_enabled_at,
    )


@router.post(
    "/mfa/disable",
    response_model=UserOut,
    summary="Desactivar MFA (requiere privilegios o confirmación)",
)
def mfa_disable(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Desactiva MFA para el usuario actual.
    Si la política global exige MFA para su rol, en su siguiente login deberá
    volver a enrolarse obligatoriamente.
    """
    mfa.reset_user_mfa(current_user)
    db.commit()
    db.refresh(current_user)
    logger.info("MFA desactivado para usuario: %s", current_user.email)
    return current_user


@router.get(
    "/me",
    response_model=UserOut,
    summary="Perfil del usuario autenticado",
)
def me(current_user: User = Depends(get_current_user)):
    """Devuelve los datos del usuario dueño del JWT proporcionado."""
    return current_user
