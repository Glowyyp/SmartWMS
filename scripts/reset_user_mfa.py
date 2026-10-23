"""
scripts/reset_user_mfa.py — Herramienta CLI de recuperación y administración de MFA

Uso:
  python scripts\\reset_user_mfa.py <email_usuario>
  python scripts\\reset_user_mfa.py --list

Permite desvincular el autenticador TOTP de un usuario en caso de pérdida
o daño de su teléfono móvil, o visualizar el estado MFA de todas las cuentas.
"""

from __future__ import annotations

import os
import sys

# Ajustar sys.path para importar módulos de backend
script_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(script_dir)
backend_dir = os.path.join(root_dir, "ecommerce", "backend")
sys.path.insert(0, backend_dir)

from app.core.env import load_project_env
load_project_env()

from app.database import SessionLocal
from app.models.user import User
from app.core import mfa


def list_users_mfa():
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        print("\n" + "=" * 78)
        print(f"{'ID':<4} {'EMAIL':<32} {'ROL':<12} {'MFA ACTIVO':<12} {'CÓDIGOS':<8}")
        print("=" * 78)
        for u in users:
            remaining = mfa.remaining_recovery_codes(u.mfa_recovery_codes)
            mfa_str = "SÍ (Activo)" if u.mfa_enabled else "NO (Pendiente)"
            print(f"{u.id:<4} {u.email:<32} {u.role:<12} {mfa_str:<12} {remaining:<8}")
        print("=" * 78 + "\n")
    finally:
        db.close()


def reset_user(email: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email.strip()).first()
        if not user:
            print(f"[ERROR] No existe usuario con email: '{email}'")
            sys.exit(1)

        mfa.reset_user_mfa(user)
        db.commit()
        print(f"\n[OK] MFA restablecido con éxito para: {user.email} (Rol: {user.role})")
        print("     El usuario podrá iniciar sesión con su contraseña y se le solicitará")
        print("     vincular un nuevo autenticador (Google Authenticator / Microsoft / Aegis).\n")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    arg = sys.argv[1].strip()
    if arg in ("--list", "-l"):
        list_users_mfa()
    else:
        reset_user(arg)
