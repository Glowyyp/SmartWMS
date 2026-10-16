"""
models/inventory.py — Modelo ORM para el Inventario de Productos

Tabla maestra de stock. Usamos SELECT FOR UPDATE al descontar unidades
para garantizar consistencia bajo concurrencia (múltiples webhooks simultáneos).
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Numeric, DateTime, func, Text, Boolean
from app.database import Base


class ProductInventory(Base):
    __tablename__ = "product_inventory"

    id = Column(Integer, primary_key=True, index=True)

    # SKU: identificador único del producto
    sku = Column(String(100), unique=True, nullable=False, index=True)

    # Nombre descriptivo del producto
    product_name = Column(String(300), nullable=False)

    # Stock actual disponible
    stock_quantity = Column(Integer, nullable=False, default=0)

    # Precio de referencia (puede diferir del precio de venta en el webhook)
    unit_price = Column(Numeric(precision=12, scale=2), nullable=False)

    # Umbral mínimo para alertas de stock bajo
    reorder_point = Column(Integer, nullable=False, default=10)

    # Ubicación física en el almacén (zona/pasillo). Ej: 'A', 'B', 'C-01', etc.
    # NULL = sin ubicación asignada. Se muestra en el botón ❓ del Operario.
    warehouse_location = Column(String(50), nullable=True, default=None)

    # Stock pendiente (unidades que se esperan recibir)
    pending_quantity = Column(Integer, nullable=False, default=0)

    # Dimensiones y Peso
    length = Column(Numeric(precision=10, scale=2), nullable=True)
    width = Column(Numeric(precision=10, scale=2), nullable=True)
    height = Column(Numeric(precision=10, scale=2), nullable=True)
    dimensions_unit = Column(String(10), nullable=False, default="cm")
    
    # Volumen estimado en cm³ (length * width * height)
    estimated_volume = Column(Numeric(precision=12, scale=2), nullable=True)
    
    weight = Column(Numeric(precision=10, scale=3), nullable=True)
    weight_unit = Column(String(10), nullable=False, default="kg")
    
    has_box = Column(Boolean, nullable=False, default=True)

    # Timestamps de auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def is_low_stock(self) -> bool:
        """True si el stock actual está en o por debajo del reorder point."""
        return self.stock_quantity <= self.reorder_point

    def __repr__(self) -> str:
        return f"<ProductInventory sku={self.sku} stock={self.stock_quantity}>"
