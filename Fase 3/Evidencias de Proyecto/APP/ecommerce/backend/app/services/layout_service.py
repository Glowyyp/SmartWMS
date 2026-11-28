"""
services/layout_service.py — Inicialización y sincronización del Layout y Ubicaciones
"""

from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.inventory import ProductInventory
from app.models.warehouse import ProductLocationStock, WarehouseLocation, WarehouseZone

logger = logging.getLogger(__name__)

DEFAULT_ZONES = [
    {"code": "A", "name": "Zona A — Insumos",     "color": "#6366f1", "racks": ["A-01", "A-02", "A-03"]},
    {"code": "B", "name": "Zona B — Electrónica", "color": "#8b5cf6", "racks": ["B-01", "B-02", "B-03", "B-04"]},
    {"code": "C", "name": "Zona C — Periféricos", "color": "#06b6d4", "racks": ["C-01", "C-02", "C-03"]},
    {"code": "D", "name": "Zona D — Cuarentena",  "color": "#f59e0b", "racks": ["D-01", "D-02"]},
]

DEFAULT_TABLES = [
    {"code": "M-01", "name": "Mesa 1"},
    {"code": "M-02", "name": "Mesa 2"},
    {"code": "M-03", "name": "Mesa 3"},
    {"code": "M-04", "name": "Mesa 4"},
]


def ensure_default_layout(db: Session) -> None:
    """
    Crea las 4 mesas predeterminadas (M-01..M-04) y las zonas/racks iniciales
    si aún no existen ubicaciones en la BD. Idempotente: no duplica ni
    recrea elementos eliminados una vez inicializado el layout.
    """
    existing_locations = db.query(WarehouseLocation).count()
    existing_zones = db.query(WarehouseZone).count()
    if existing_locations > 0 or existing_zones > 0:
        return

    for t in DEFAULT_TABLES:
        db.add(WarehouseLocation(code=t["code"], name=t["name"], location_type="table", zone_id=None))

    for z in DEFAULT_ZONES:
        zone = WarehouseZone(code=z["code"], name=z["name"], color=z["color"])
        db.add(zone)
        db.flush()
        for rack_code in z["racks"]:
            db.add(WarehouseLocation(
                code=rack_code,
                name=f"Estantería {rack_code}",
                location_type="rack",
                zone_id=zone.id,
            ))

    db.commit()
    logger.info("✅ Layout inicial de bodega creado (4 mesas M-01..M-04 y %d zonas).", len(DEFAULT_ZONES))


def sync_product_warehouse_location_summary(product: ProductInventory, db: Session) -> str | None:
    """
    Actualiza ProductInventory.warehouse_location a partir de sus ubicaciones activas
    en product_location_stocks, ordenadas de mayor a menor cantidad.
    """
    rows = (
        db.query(ProductLocationStock, WarehouseLocation)
        .join(WarehouseLocation, WarehouseLocation.id == ProductLocationStock.location_id)
        .filter(ProductLocationStock.sku == product.sku, ProductLocationStock.quantity > 0)
        .order_by(ProductLocationStock.quantity.desc(), WarehouseLocation.code.asc())
        .all()
    )
    if not rows:
        return product.warehouse_location

    codes = [loc.code for _, loc in rows]
    summary = ", ".join(codes)
    if len(summary) > 50:
        summary = f"{codes[0]} (+{len(codes) - 1})"
    product.warehouse_location = summary
    return summary


def reconcile_location_stocks_after_dispatch(product: ProductInventory, db: Session) -> None:
    """
    Cuando un despacho reduce product.stock_quantity por debajo de la suma
    ubicada en product_location_stocks, descuenta el excedente de las ubicaciones
    asignadas para mantener sum(location_stocks) <= product.stock_quantity.
    """
    rows = (
        db.query(ProductLocationStock)
        .filter(ProductLocationStock.sku == product.sku, ProductLocationStock.quantity > 0)
        .order_by(ProductLocationStock.stored_at.asc(), ProductLocationStock.id.asc())
        .all()
    )
    if not rows:
        return

    located_total = sum(r.quantity for r in rows)
    excess = located_total - max(0, product.stock_quantity)
    if excess <= 0:
        return

    for r in rows:
        if excess <= 0:
            break
        deduct = min(r.quantity, excess)
        r.quantity -= deduct
        excess -= deduct
        if r.quantity == 0:
            db.delete(r)

    db.flush()
    remaining_active = (
        db.query(ProductLocationStock)
        .filter(ProductLocationStock.sku == product.sku, ProductLocationStock.quantity > 0)
        .count()
    )
    if remaining_active == 0:
        product.warehouse_location = None
    else:
        sync_product_warehouse_location_summary(product, db)


def get_located_qty_by_sku(db: Session, skus: List[str] | None = None) -> Dict[str, List[dict]]:
    """Retorna desglose de ubicaciones activas agrupado por SKU."""
    query = (
        db.query(ProductLocationStock, WarehouseLocation, WarehouseZone)
        .join(WarehouseLocation, WarehouseLocation.id == ProductLocationStock.location_id)
        .outerjoin(WarehouseZone, WarehouseZone.id == WarehouseLocation.zone_id)
        .filter(ProductLocationStock.quantity > 0)
    )
    if skus is not None:
        if not skus:
            return {}
        query = query.filter(ProductLocationStock.sku.in_(skus))

    rows = query.order_by(ProductLocationStock.quantity.desc(), WarehouseLocation.code.asc()).all()
    grouped: Dict[str, List[dict]] = {}
    for stock_row, loc, zone in rows:
        grouped.setdefault(stock_row.sku, []).append({
            "location_id": loc.id,
            "location_code": loc.code,
            "location_name": loc.name,
            "location_type": loc.location_type,
            "zone_code": zone.code if zone else None,
            "quantity": stock_row.quantity,
            "stored_at": stock_row.stored_at,
        })
    return grouped
