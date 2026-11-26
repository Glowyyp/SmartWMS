"""
routers/users.py — Gestión de Usuarios (Admin/Supervisor only)

GET /api/v1/users        → Listar todos los usuarios con datos y roles
GET /api/v1/users/{id}   → Detalle de un usuario
PATCH /api/v1/users/{id}/activate   → Activar/desactivar usuario (solo admin)
"""

from __future__ import annotations

import logging
from typing import List, Union

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.presence import compute_user_online
from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user, require_admin, require_supervisor_or_admin
from app.schemas.auth import UserOut, AdminUserOut, SupervisorUserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["Usuarios"])


def _serialize_user(user: User, viewer_role: str) -> Union[UserOut, SupervisorUserOut]:
    online = compute_user_online(user)
    if viewer_role == "admin":
        out = UserOut.model_validate(user)
        out.is_online = online
        return out
    display = (user.full_name or "").strip() or user.email.split("@")[0]
    return SupervisorUserOut(
        id=user.id,
        username=display,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        is_online=online,
        last_login_at=user.last_login_at,
        last_seen_at=user.last_seen_at,
    )


@router.get(
    "",
    response_model=List[Union[UserOut, SupervisorUserOut]],
    summary="Listar usuarios permitidos según el rol",
)
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """
    - Administradores: ven todos los usuarios del sistema.
    - Supervisores: solo pueden consultar supervisores y operarios (nunca administradores).
    """
    query = db.query(User)
    if current_user.role != "admin":
        query = query.filter(User.role.in_(["supervisor", "operario"]))
    users = query.order_by(User.created_at.desc()).all()
    return [_serialize_user(u, current_user.role) for u in users]


@router.get(
    "/admin-view",
    response_model=List[AdminUserOut],
    summary="Listar usuarios con hash de contraseña (solo admin/dev)",
    tags=["Usuarios"],
)
def list_users_admin(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    **Solo para administradores y desarrollo.**
    Retorna todos los usuarios incluyendo el `hashed_password` (bcrypt).
    útil para verificar contraseñas durante el desarrollo o para
    consultarlas en Swagger sin necesidad de acceso directo a la BD.
    """
    users = db.query(User).order_by(User.created_at.desc()).all()
    return users


@router.get(
    "/{user_id}",
    response_model=Union[UserOut, SupervisorUserOut],
    summary="Detalle de un usuario",
)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_supervisor_or_admin),
):
    """Retorna los datos de un usuario específico por ID (supervisores no ven admins)."""
    query = db.query(User).filter(User.id == user_id)
    if current_user.role != "admin":
        query = query.filter(User.role.in_(["supervisor", "operario"]))
    user = query.first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con id={user_id} no encontrado",
        )
    return _serialize_user(user, current_user.role)


@router.patch(
    "/{user_id}/activate",
    response_model=UserOut,
    summary="Activar o desactivar un usuario",
)
def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Alterna el estado activo/inactivo de un usuario. Solo admin."""
    query = db.query(User).filter(User.id == user_id)
    if admin_user.role != "admin":
        query = query.filter(User.role.in_(["supervisor", "operario"]))
    user = query.first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con id={user_id} no encontrado",
        )
    user.is_active = not user.is_active
    db.commit()
    db.refresh(user)
    state = "activado" if user.is_active else "desactivado"
    logger.info("Usuario %s: %s", user.email, state)
    return user


@router.post(
    "/{user_id}/reset-mfa",
    response_model=UserOut,
    summary="Restablecer MFA de un usuario (admin o supervisor)",
)
def reset_user_mfa_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_supervisor_or_admin),
):
    """
    Procedimiento de recuperación administrativo:
    Desvincula el autenticador TOTP y códigos del usuario especificado.
    En su siguiente inicio de sesión, el usuario podrá volver a vincular un nuevo autenticador.
    """
    from app.core import mfa

    query = db.query(User).filter(User.id == user_id)
    if admin_user.role != "admin":
        query = query.filter(User.role.in_(["supervisor", "operario"]))
    user = query.first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con id={user_id} no encontrado",
        )
    mfa.reset_user_mfa(user)
    db.commit()
    db.refresh(user)
    logger.warning(
        "MFA restablecido para %s por orden de %s (%s)",
        user.email,
        admin_user.email,
        admin_user.role,
    )
    return user

