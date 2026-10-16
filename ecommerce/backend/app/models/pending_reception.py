"""
models/pending_reception.py — Modelo ORM para Recepciones de Stock Pendiente
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Text
from sqlalchemy.orm import relationship
from app.database import Base


class PendingReception(Base):
    __tablename__ = "pending_receptions"

    id = Column(Integer, primary_key=True, index=True)

    # Producto relacionado (por SKU)
    sku = Column(String(100), nullable=False, index=True)

    # Cantidades
    expected_quantity = Column(Integer, nullable=False)
    received_quantity = Column(Integer, nullable=False, default=0)

    # Fecha estimada de llegada
    expected_date = Column(DateTime(timezone=True), nullable=True)

    # Estado: pending | partial | completed | cancelled
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Observaciones opcionales (proveedor, orden de compra, etc)
    notes = Column(Text, nullable=True)

    # Usuarios
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    received_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    received_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PendingReception id={self.id} sku={self.sku} expected={self.expected_quantity} status={self.status}>"
