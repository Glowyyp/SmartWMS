"""
routers/auth.py — Endpoints de Autenticación

POST /api/auth/register  → Registrar usuario (admin | supervisor | operario)
POST /api/auth/login     → Login, devuelve JWT + role (para Angular)
GET  /api/auth/me        → Perfil del usuario autenticado
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models.user import User
from app.schemas.auth import TokenResponse, UserCreate, UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])

# Extrae el token del header Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ─── Dependencia: usuario autenticado ─────────────────────────────────────────

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependencia reutilizable que valida el JWT y retorna el usuario activo.
    Lanza 401 si el token es inválido o el usuario no existe/está inactivo.
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
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


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Crea un nuevo usuario. El email debe ser único.
    Roles válidos: 'admin', 'supervisor', 'operario'.
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
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("Usuario registrado: %s (%s)", user.email, user.role)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login y obtención de JWT",
)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Autentica con email (username) y contraseña.
    Devuelve JWT Bearer + el campo 'role' para que Angular pueda redirigir
    al panel correcto (supervisor / operario) sin necesidad de decodificar el token.
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
            detail="Cuenta desactivada",
        )

    token = create_access_token({"sub": user.email, "role": user.role})
    logger.info("Login exitoso: %s (%s)", user.email, user.role)
    # role se devuelve explícitamente en el response para Angular
    return TokenResponse(access_token=token, role=user.role)


@router.get(
    "/me",
    response_model=UserOut,
    summary="Perfil del usuario autenticado",
)
def me(current_user: User = Depends(get_current_user)):
    """Devuelve los datos del usuario dueño del JWT proporcionado."""
    return current_user
