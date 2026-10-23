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
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Numeric, desc
from sqlalchemy.orm import relationship
from app.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)

    # Número visible para los usuarios: WO-0001, WO-0002, etc.
    order_number = Column(String(20), unique=True, nullable=False, index=True)

    # Estado del pedido:
    # por_asignar (sin operario) | pending (asignado, listo para picking) |
    # in_preparation (en proceso de picking/packing) | dispatched (completado) | cancelled | waiting_stock
    status = Column(String(30), nullable=False, default="por_asignar", index=True)

    # Usuario Supervisor que creó el pedido
    created_by_id  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_email = Column(String(254), nullable=True)   # desnormalizado para lectura rápida

    # Operario asignado por el supervisor (NULL = sin asignar)
    assigned_operario_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_operario_email = Column(String(254), nullable=True)

    # Usuario Operario que realizó el despacho (NULL hasta que se despacha)
    dispatched_by_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    dispatched_by_email = Column(String(254), nullable=True)  # desnormalizado

    # Usuario que canceló el pedido (NULL si no está cancelado)
    cancelled_by_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cancelled_by_email = Column(String(254), nullable=True)

    # Timestamps
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at  = Column(DateTime(timezone=True), nullable=True)

    # Relación 1:N con historial de cambios de estado
    status_history = relationship(
        "WorkOrderStatusHistory",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="desc(WorkOrderStatusHistory.id)",
    )

    # Relación 1:N con ítems
    items = relationship(
        "WorkOrderItem",
        back_populates="work_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Dimensiones globales calculadas y despachadas
    total_weight = Column(Numeric(precision=10, scale=3), nullable=True)
    total_volume = Column(Numeric(precision=10, scale=2), nullable=True)
    packages_count = Column(Integer, nullable=False, default=0)

    # Relación 1:N con bultos
    packages = relationship(
        "WorkOrderPackage",
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


class WorkOrderPackage(Base):
    __tablename__ = "work_order_packages"

    id = Column(Integer, primary_key=True, index=True)

    work_order_id = Column(
        Integer,
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Dimensiones físicas del bulto final
    length = Column(Numeric(precision=10, scale=2), nullable=True)
    width = Column(Numeric(precision=10, scale=2), nullable=True)
    height = Column(Numeric(precision=10, scale=2), nullable=True)
    weight = Column(Numeric(precision=10, scale=3), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    work_order = relationship("WorkOrder", back_populates="packages")

    def __repr__(self) -> str:
        return f"<WorkOrderPackage id={self.id} wo_id={self.work_order_id}>"


class WorkOrderStatusHistory(Base):
    __tablename__ = "work_order_status_history"

    id = Column(Integer, primary_key=True, index=True)

    work_order_id = Column(
        Integer,
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    from_status = Column(String(30), nullable=True)
    to_status = Column(String(30), nullable=False)
    changed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_email = Column(String(254), nullable=True)
    notes = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    work_order = relationship("WorkOrder", back_populates="status_history")

    def __repr__(self) -> str:
        return f"<WorkOrderStatusHistory wo={self.work_order_id} {self.from_status}->{self.to_status} by={self.changed_by_email}>"

