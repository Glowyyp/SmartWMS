"""
routers/inventory.py — CRUD REST de Inventario

GET    /api/v1/inventory       → Listar productos (requiere JWT)
POST   /api/v1/inventory       → Agregar producto (requiere JWT admin)
PUT    /api/v1/inventory/{id}  → Editar producto   (requiere JWT admin)
DELETE /api/v1/inventory/{id}  → Eliminar producto (requiere JWT admin)
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.work_order import WorkOrder, WorkOrderItem
from app.routers.auth import get_current_user, require_admin, require_supervisor_or_admin
from app.schemas.inventory import ProductCreate, ProductOut, ProductUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventario"])


# ─── GET /api/v1/inventory ────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[ProductOut],
    summary="Listar todos los productos con stock físico, reservado y disponible",
)
def list_products(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),   # cualquier usuario autenticado
):
    """
    Devuelve todos los productos del inventario ordenados por SKU.
    Incluye reserved_qty (suma de pedidos pendientes) y available_qty calculados
    con una sola consulta GROUP BY — sin N+1 queries.
    """
    products = db.query(ProductInventory).order_by(ProductInventory.sku).all()

    # Una sola query para obtener el total reservado por SKU
    reserved_by_sku: dict[str, int] = {}
    rows = db.execute(
        select(WorkOrderItem.sku, func.sum(WorkOrderItem.quantity).label("reserved"))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status == "pending")
        .group_by(WorkOrderItem.sku)
    ).all()
    for row in rows:
        reserved_by_sku[row.sku] = int(row.reserved)

    result = []
    for p in products:
        reserved = reserved_by_sku.get(p.sku, 0)
        out = ProductOut.model_validate(p)
        out.reserved_qty  = reserved
        out.available_qty = max(0, p.stock_quantity - reserved)
        result.append(out)

    return result


# ─── POST /api/v1/inventory ───────────────────────────────────────────────────

@router.post(
    "",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar producto al inventario",
)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    """Crea un nuevo producto. El SKU debe ser único. Requiere rol supervisor o admin."""
    existing = db.query(ProductInventory).filter(
        ProductInventory.sku == product_in.sku
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un producto con SKU '{product_in.sku}'",
        )

    product = ProductInventory(**product_in.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    logger.info("📦 Producto creado: %s — %s", product.sku, product.product_name)
    return product


# ─── PUT /api/v1/inventory/{id} ───────────────────────────────────────────────

@router.put(
    "/{product_id}",
    response_model=ProductOut,
    summary="Editar producto del inventario",
)
def update_product(
    product_id: int,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    """Actualiza los campos indicados del producto. Requiere rol supervisor o admin."""
    product = db.query(ProductInventory).filter(
        ProductInventory.id == product_id
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con id={product_id} no encontrado",
        )

    update_data = product_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    logger.info("✏️  Producto actualizado: id=%d SKU=%s", product.id, product.sku)
    return product


# ─── DELETE /api/v1/inventory/{id} ────────────────────────────────────────────

@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar producto del inventario",
)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_admin),
):
    """Elimina un producto permanentemente. Requiere rol admin."""
    product = db.query(ProductInventory).filter(
        ProductInventory.id == product_id
    ).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Producto con id={product_id} no encontrado",
        )

    db.delete(product)
    db.commit()
    logger.info("🗑️  Producto eliminado: id=%d SKU=%s", product_id, product.sku)
