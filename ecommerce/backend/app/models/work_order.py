"""
models/work_order.py — Modelo ORM para Pedidos de Bodega (Work Orders)

Un WorkOrder es creado por el Supervisor desde el panel web.
El Operario lo visualiza y ejecuta el despacho físico.

Estados:
  pending     → Creado, reserva stock, aún no despachado
  dispatched  → Operario ejecutó el despacho; stock descontado físicamente
  cancelled   → Cancelado; reserva liberada automáticamente

El stock_quantity de ProductInventory es el stock FÍSICO real.
El stock RESERVADO se calcula con SUM(qty) de WorkOrderItems en estado 'pending'.
El stock DISPONIBLE = stock_quantity - reservado.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from app.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)

    # Número visible para los usuarios: WO-0001, WO-0002, etc.
    order_number = Column(String(20), unique=True, nullable=False, index=True)

    # Estado del pedido
    # pending | dispatched | cancelled
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Usuario Supervisor que creó el pedido
    created_by_id  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_email = Column(String(254), nullable=True)   # desnormalizado para lectura rápida

    # Operario asignado por el supervisor (NULL = cualquier operario puede verlo)
    assigned_operario_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_operario_email = Column(String(254), nullable=True)

    # Usuario Operario que realizó el despacho (NULL hasta que se despacha)
    dispatched_by_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dispatched_by_email = Column(String(254), nullable=True)  # desnormalizado

    # Timestamps
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at  = Column(DateTime(timezone=True), nullable=True)


    # Relación 1:N con ítems
    items = relationship(
        "WorkOrderItem",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<WorkOrder {self.order_number} status={self.status}>"


class WorkOrderItem(Base):
    __tablename__ = "work_order_items"

    id = Column(Integer, primary_key=True, index=True)

    work_order_id = Column(
        Integer,
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Referencia al inventario por SKU (sin FK dura para flexibilidad)
    sku          = Column(String(100), nullable=False, index=True)
    product_name = Column(String(300), nullable=False)   # desnormalizado para evitar JOIN
    quantity     = Column(Integer, nullable=False)

    work_order = relationship("WorkOrder", back_populates="items")

    def __repr__(self) -> str:
        return f"<WorkOrderItem sku={self.sku} qty={self.quantity}>"
