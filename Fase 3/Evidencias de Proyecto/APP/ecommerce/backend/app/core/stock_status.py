"""
core/stock_status.py — Clasificación centralizada de estados de stock (3 niveles).

Fuente única de verdad compartida entre modelos ORM, routers de inventario/pedidos,
layout y frontend:

  - critical ("Crítico", rojo):
      stock disponible <= 0  o  stock disponible <= reorder_point
  - warning  ("Advertencia", amarillo):
      reorder_point > 0  y  reorder_point < stock disponible <= reorder_point * 2
  - healthy  ("Saludable", verde):
      stock disponible > reorder_point * 2  (y stock disponible > 0)
"""

from __future__ import annotations

from typing import Literal

StockStatus = Literal["healthy", "warning", "critical"]

WARNING_MULTIPLIER = 2


def get_warning_threshold(reorder_point: int | None) -> int:
    """Umbral superior del rango amarillo (Advertencia)."""
    rp = max(0, int(reorder_point or 0))
    return rp * WARNING_MULTIPLIER


def compute_stock_status(quantity: int | None, reorder_point: int | None) -> StockStatus:
    """
    Calcula el estado canónico de stock en 3 niveles bien diferenciados:
      - 'critical' : <= 0 o <= reorder_point
      - 'warning'  : > reorder_point y <= reorder_point * 2
      - 'healthy'  : > reorder_point * 2 (y > 0)
    """
    qty = max(0, int(quantity or 0))
    rp = max(0, int(reorder_point or 0))

    if qty <= 0 or qty <= rp:
        return "critical"
    if rp > 0 and qty <= get_warning_threshold(rp):
        return "warning"
    return "healthy"


def sync_inventory_stock_statuses(db, skus: list[str] | None = None) -> int:
    """
    Sincroniza la columna persistida product_inventory.stock_status usando el stock
    disponible real (stock_quantity - reserved_qty) para evitar cualquier discrepancia
    entre el estado almacenado en BD y el estado mostrado en la UI.
    """
    from sqlalchemy import func, select
    from app.models.inventory import ProductInventory
    from app.models.work_order import WorkOrder, WorkOrderItem

    active_reserved = [
        "pending",
        "waiting_stock",
        "por_asignar",
        "assigned",
        "in_preparation",
        "in_progress",
    ]

    prod_q = db.query(ProductInventory)
    if skus is not None:
        if not skus:
            return 0
        prod_q = prod_q.filter(ProductInventory.sku.in_(skus))
    products = prod_q.all()
    if not products:
        return 0

    res_q = (
        select(WorkOrderItem.sku, func.sum(WorkOrderItem.quantity).label("reserved"))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status.in_(active_reserved))
        .group_by(WorkOrderItem.sku)
    )
    if skus is not None:
        res_q = res_q.where(WorkOrderItem.sku.in_(skus))

    reserved_by_sku = {row.sku: int(row.reserved or 0) for row in db.execute(res_q).all()}

    updated = 0
    for prod in products:
        avail = max(0, int(prod.stock_quantity or 0) - reserved_by_sku.get(prod.sku, 0))
        computed = compute_stock_status(avail, prod.reorder_point)
        if prod.stock_status != computed:
            prod.stock_status = computed
            updated += 1
    return updated
