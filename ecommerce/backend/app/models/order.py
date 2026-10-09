"""
models/order.py — Modelo ORM para la tabla de Órdenes

Registra la cabecera de cada orden recibida via webhook.
La relación con OrderItem es lazy-loaded para evitar N+1 en listados.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, func
from sqlalchemy.orm import relationship
from app.database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)

    # Identificador externo que llega en el payload del webhook
    external_order_id = Column(String(100), unique=True, nullable=False, index=True)

    # Datos del cliente (desnormalizados para simplicidad; en producción sería FK a customers)
    customer_id = Column(String(100), nullable=False)
    customer_name = Column(String(200), nullable=False)
    customer_email = Column(String(254), nullable=False)

    # Financiero
    total = Column(Numeric(precision=12, scale=2), nullable=False)

    # Estado de la orden
    status = Column(String(50), nullable=False, default="received")
    # Posibles valores: received | processing | completed | cancelled | failed

    # Timestamps
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    event_timestamp = Column(DateTime(timezone=True), nullable=False)
    # event_timestamp: el timestamp que venía en el payload original del webhook

    # Relación 1:N con los items
    items = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",  # Carga items en la misma query usando SELECT IN (evita N+1)
    )

    def __repr__(self) -> str:
        return f"<Order id={self.id} external_id={self.external_order_id} status={self.status}>"
