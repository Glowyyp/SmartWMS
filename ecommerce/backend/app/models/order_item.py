"""
models/order_item.py — Modelo ORM para los ítems de cada orden

Cada fila representa un SKU dentro de una orden.
Tiene FK hacia Order (cascade delete) y referencia lógica a ProductInventory via SKU.
"""

from sqlalchemy import Column, Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)

    # FK a la orden padre
    order_id = Column(
        Integer,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Referencia al inventario (lógica, sin FK dura para permitir productos aún no cargados)
    sku = Column(String(100), nullable=False, index=True)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(precision=12, scale=2), nullable=False)
    subtotal = Column(Numeric(precision=12, scale=2), nullable=False)

    # Relación inversa hacia Order
    order = relationship("Order", back_populates="items")

    def __repr__(self) -> str:
        return f"<OrderItem id={self.id} sku={self.sku} qty={self.quantity}>"
