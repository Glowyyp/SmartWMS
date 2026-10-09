"""
models/user.py — Modelo ORM para la tabla de Usuarios

Roles unificados en todo el sistema: 'admin' | 'supervisor' | 'operario'.
Las contraseñas se almacenan como hash bcrypt (nunca en texto plano).
"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String(254), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name      = Column(String(200), nullable=True)
    role           = Column(String(50),  nullable=False, default="operario")
    # roles posibles: 'admin' | 'supervisor' | 'operario'

    is_active      = Column(Boolean, default=True, nullable=False)

    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(),
                            onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
