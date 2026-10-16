"""
schemas/inventory.py — Pydantic schemas para el CRUD de Inventario

ProductCreate  → body del POST (crear producto)
ProductUpdate  → body del PUT (editar stock / precio)
ProductOut     → respuesta pública (incluye id, timestamps y stock reservado/disponible)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


# ─── Entrada ──────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    """Payload para agregar un nuevo producto al inventario."""
    sku: str = Field(min_length=1, max_length=100, examples=["SKU-001"])
    product_name: str = Field(min_length=1, max_length=300)
    stock_quantity: int = Field(ge=0, default=0)
    unit_price: Decimal = Field(gt=0, decimal_places=2)
    reorder_point: int = Field(ge=0, default=10)
    warehouse_location: str | None = Field(default=None, max_length=50, description="Zona/ubicación física del almacén. Ej: 'A', 'B', 'C-01'")
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    dimensions_unit: str = "cm"
    estimated_volume: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str = "kg"
    has_box: bool = True


class ProductUpdate(BaseModel):
    """Campos editables de un producto (todos opcionales)."""
    product_name: str | None = Field(default=None, max_length=300)
    stock_quantity: int | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    reorder_point: int | None = Field(default=None, ge=0)
    warehouse_location: str | None = Field(default=None, max_length=50)
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    dimensions_unit: str | None = None
    estimated_volume: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str | None = None
    has_box: bool | None = None


# ─── Salida ───────────────────────────────────────────────────────────────────

class ProductOut(BaseModel):
    """
    Representación completa de un producto del inventario.

    stock_quantity  → Stock FÍSICO real (se descuenta al despachar).
    reserved_qty    → Suma de unidades reservadas por pedidos pendientes.
    available_qty   → stock_quantity - reserved_qty (stock disponible para nuevos pedidos).
    """
    id: int
    sku: str
    product_name: str
    stock_quantity: int
    unit_price: Decimal
    reorder_point: int
    is_low_stock: bool
    warehouse_location: str | None = None
    pending_quantity: int = 0
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    dimensions_unit: str = "cm"
    estimated_volume: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str = "kg"
    has_box: bool = True
    created_at: datetime
    updated_at: datetime

    # Campos calculados dinámicamente por el router (no están en el ORM)
    reserved_qty: int = 0
    available_qty: int = 0

    model_config = {"from_attributes": True}


# ─── Pending Reception ────────────────────────────────────────────────────────

class PendingReceptionCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    expected_quantity: int = Field(gt=0)
    expected_date: datetime | None = None
    notes: str | None = None

class PendingReceptionConfirm(BaseModel):
    received_quantity: int = Field(ge=0)

class PendingReceptionOut(BaseModel):
    id: int
    sku: str
    expected_quantity: int
    received_quantity: int
    expected_date: datetime | None = None
    status: str
    notes: str | None = None
    created_by_id: int | None = None
    received_by_id: int | None = None
    created_at: datetime
    updated_at: datetime
    received_at: datetime | None = None

    model_config = {"from_attributes": True}
