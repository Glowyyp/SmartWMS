"""
routers/layout.py — Administración dinámica del Layout del Almacén (Zonas, Estanterías y Mesas)

Endpoints:
  GET    /api/v1/layout                         → Estructura completa (mesas, zonas, racks, stock por ubicación, movimientos)
  GET    /api/v1/layout/locations/{id}/items    → Contenido detallado de una ubicación específica
  POST   /api/v1/layout/tables                  → Crear mesa (Supervisor/Admin)
  PUT    /api/v1/layout/tables/{id}             → Editar mesa (Supervisor/Admin)
  DELETE /api/v1/layout/tables/{id}             → Eliminar mesa vacía (Supervisor/Admin)
  POST   /api/v1/layout/zones                   → Crear zona + racks opcionales (Supervisor/Admin)
  PUT    /api/v1/layout/zones/{id}              → Editar zona (Supervisor/Admin)
  DELETE /api/v1/layout/zones/{id}              → Eliminar zona vacía (Supervisor/Admin)
  POST   /api/v1/layout/zones/{zone_id}/racks   → Agregar estantería a zona (Supervisor/Admin)
  PUT    /api/v1/layout/racks/{id}              → Editar estantería (Supervisor/Admin)
  DELETE /api/v1/layout/racks/{id}              → Eliminar estantería vacía (Supervisor/Admin)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.warehouse import ProductLocationStock, PutawayMovement, WarehouseLocation, WarehouseZone
from app.models.work_order import WorkOrder, WorkOrderItem
from app.routers.auth import get_current_user, require_supervisor_or_admin
from app.services.layout_service import ensure_default_layout, sync_product_warehouse_location_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/layout", tags=["Layout del Almacén"])

ACTIVE_RESERVED_STATUSES = [
    "pending",
    "waiting_stock",
    "por_asignar",
    "assigned",
    "in_preparation",
    "in_progress",
]


# ─── Schemas ──────────────────────────────────────────────────────────────────

class LocationItemDetailOut(BaseModel):
    sku: str
    product_name: str
    quantity: int
    stored_at: datetime
    stock_quantity: int
    reserved_qty: int
    available_qty: int
    unit_price: float
    reorder_point: int
    stock_status: str = "healthy"
    is_low_stock: bool


class LayoutLocationOut(BaseModel):
    id: int
    code: str
    name: str
    location_type: str  # 'table' | 'rack'
    zone_id: Optional[int] = None
    zone_code: Optional[str] = None
    zone_name: Optional[str] = None
    occupied_skus_count: int = 0
    total_units: int = 0
    is_occupied: bool = False
    items: List[LocationItemDetailOut] = []


class LayoutZoneOut(BaseModel):
    id: int
    code: str
    name: str
    color: str
    racks: List[LayoutLocationOut] = []
    total_units: int = 0
    occupied_racks_count: int = 0


class PutawayMovementOut(BaseModel):
    id: int
    sku: str
    product_name: str
    quantity: int
    source_location_code: Optional[str] = None
    destination_location_code: str
    performed_by_email: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LayoutOverviewOut(BaseModel):
    tables: List[LayoutLocationOut] = []
    zones: List[LayoutZoneOut] = []
    movements: List[PutawayMovementOut] = []


class TableCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, max_length=100)


class TableUpdateIn(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)


class ZoneCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#6366f1", max_length=20)
    racks: List[str] = []


class ZoneUpdateIn(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=20)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, max_length=20)


class RackCreateIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, max_length=100)


class RackUpdateIn(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_reserved_map(db: Session) -> dict[str, int]:
    rows = (
        db.query(WorkOrderItem.sku, func.sum(WorkOrderItem.quantity).label("reserved"))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .filter(WorkOrder.status.in_(ACTIVE_RESERVED_STATUSES))
        .group_by(WorkOrderItem.sku)
        .all()
    )
    return {r.sku: int(r.reserved) for r in rows}


from app.core.stock_status import compute_stock_status

def _serialize_location(
    loc: WarehouseLocation,
    zone: WarehouseZone | None,
    stocks_by_loc: dict[int, List[tuple[ProductLocationStock, ProductInventory]]],
    reserved_by_sku: dict[str, int],
) -> LayoutLocationOut:
    items: List[LocationItemDetailOut] = []
    total_units = 0

    for st, prod in stocks_by_loc.get(loc.id, []):
        if st.quantity <= 0:
            continue
        res_qty = reserved_by_sku.get(prod.sku, 0)
        avail_qty = max(0, prod.stock_quantity - res_qty)
        computed_status = compute_stock_status(avail_qty, prod.reorder_point)
        total_units += st.quantity
        items.append(
            LocationItemDetailOut(
                sku=prod.sku,
                product_name=prod.product_name,
                quantity=st.quantity,
                stored_at=st.stored_at,
                stock_quantity=prod.stock_quantity,
                reserved_qty=res_qty,
                available_qty=avail_qty,
                unit_price=float(prod.unit_price),
                reorder_point=prod.reorder_point,
                stock_status=computed_status,
                is_low_stock=computed_status == "critical",
            )
        )

    return LayoutLocationOut(
        id=loc.id,
        code=loc.code,
        name=loc.name,
        location_type=loc.location_type,
        zone_id=loc.zone_id,
        zone_code=zone.code if zone else None,
        zone_name=zone.name if zone else None,
        occupied_skus_count=len(items),
        total_units=total_units,
        is_occupied=len(items) > 0,
        items=items,
    )


def _sync_location_products_after_rename(location_id: int, db: Session) -> None:
    affected_skus = [
        r.sku
        for r in db.query(ProductLocationStock.sku)
        .filter(ProductLocationStock.location_id == location_id, ProductLocationStock.quantity > 0)
        .all()
    ]
    if not affected_skus:
        return
    prods = db.query(ProductInventory).filter(ProductInventory.sku.in_(affected_skus)).all()
    for p in prods:
        sync_product_warehouse_location_summary(p, db)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=LayoutOverviewOut,
    summary="Obtener layout completo del almacén con contenido real por ubicación",
)
def get_warehouse_layout(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    ensure_default_layout(db)

    zones = db.query(WarehouseZone).order_by(WarehouseZone.code.asc()).all()
    zones_by_id = {z.id: z for z in zones}

    all_locations = db.query(WarehouseLocation).order_by(WarehouseLocation.code.asc()).all()
    stock_rows = (
        db.query(ProductLocationStock, ProductInventory)
        .join(ProductInventory, ProductInventory.sku == ProductLocationStock.sku)
        .filter(ProductLocationStock.quantity > 0)
        .order_by(ProductInventory.sku.asc())
        .all()
    )
    stocks_by_loc: dict[int, List[tuple[ProductLocationStock, ProductInventory]]] = {}
    for st, prod in stock_rows:
        stocks_by_loc.setdefault(st.location_id, []).append((st, prod))

    reserved_by_sku = _build_reserved_map(db)

    tables_out: List[LayoutLocationOut] = []
    racks_by_zone: dict[int, List[LayoutLocationOut]] = {z.id: [] for z in zones}

    for loc in all_locations:
        zone = zones_by_id.get(loc.zone_id) if loc.zone_id else None
        serialized = _serialize_location(loc, zone, stocks_by_loc, reserved_by_sku)
        if loc.location_type == "table":
            tables_out.append(serialized)
        elif loc.zone_id in racks_by_zone:
            racks_by_zone[loc.zone_id].append(serialized)

    zones_out: List[LayoutZoneOut] = []
    for z in zones:
        racks = racks_by_zone.get(z.id, [])
        zones_out.append(
            LayoutZoneOut(
                id=z.id,
                code=z.code,
                name=z.name,
                color=z.color,
                racks=racks,
                total_units=sum(r.total_units for r in racks),
                occupied_racks_count=sum(1 for r in racks if r.is_occupied),
            )
        )

    movements = (
        db.query(PutawayMovement)
        .order_by(PutawayMovement.created_at.desc(), PutawayMovement.id.desc())
        .limit(40)
        .all()
    )

    return LayoutOverviewOut(
        tables=tables_out,
        zones=zones_out,
        movements=[PutawayMovementOut.model_validate(m) for m in movements],
    )


@router.get(
    "/locations/{location_id}/items",
    response_model=LayoutLocationOut,
    summary="Detalle de productos almacenados en una mesa o estantería",
)
def get_location_items(
    location_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    loc = db.query(WarehouseLocation).filter(WarehouseLocation.id == location_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Ubicación no encontrada")
    zone = db.query(WarehouseZone).filter(WarehouseZone.id == loc.zone_id).first() if loc.zone_id else None
    stock_rows = (
        db.query(ProductLocationStock, ProductInventory)
        .join(ProductInventory, ProductInventory.sku == ProductLocationStock.sku)
        .filter(ProductLocationStock.location_id == loc.id, ProductLocationStock.quantity > 0)
        .order_by(ProductInventory.sku.asc())
        .all()
    )
    reserved_by_sku = _build_reserved_map(db)
    return _serialize_location(loc, zone, {loc.id: stock_rows}, reserved_by_sku)


# ─── Mesas CRUD ───────────────────────────────────────────────────────────────

@router.post("/tables", response_model=LayoutLocationOut, status_code=status.HTTP_201_CREATED)
def create_table(
    payload: TableCreateIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    ensure_default_layout(db)
    clean_code = payload.code.strip().upper()
    if not clean_code:
        raise HTTPException(status_code=422, detail="El código de mesa es requerido.")

    exists = db.query(WarehouseLocation).filter(func.lower(WarehouseLocation.code) == clean_code.lower()).first()
    if exists:
        raise HTTPException(status_code=409, detail=f"Ya existe una ubicación con código '{clean_code}'.")

    clean_name = (payload.name or "").strip() or f"Mesa {clean_code}"
    loc = WarehouseLocation(code=clean_code, name=clean_name, location_type="table", zone_id=None)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return _serialize_location(loc, None, {}, {})


@router.put("/tables/{table_id}", response_model=LayoutLocationOut)
def update_table(
    table_id: int,
    payload: TableUpdateIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    loc = db.query(WarehouseLocation).filter(WarehouseLocation.id == table_id, WarehouseLocation.location_type == "table").first()
    if not loc:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")

    if payload.code is not None:
        clean_code = payload.code.strip().upper()
        if not clean_code:
            raise HTTPException(status_code=422, detail="El código de mesa no puede quedar vacío.")
        dup = (
            db.query(WarehouseLocation)
            .filter(func.lower(WarehouseLocation.code) == clean_code.lower(), WarehouseLocation.id != loc.id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"Ya existe otra ubicación con código '{clean_code}'.")
        loc.code = clean_code

    if payload.name is not None:
        clean_name = payload.name.strip()
        if clean_name:
            loc.name = clean_name

    db.flush()
    _sync_location_products_after_rename(loc.id, db)
    db.commit()
    return get_location_items(loc.id, db, _)


@router.delete("/tables/{table_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table(
    table_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    loc = db.query(WarehouseLocation).filter(WarehouseLocation.id == table_id, WarehouseLocation.location_type == "table").first()
    if not loc:
        raise HTTPException(status_code=404, detail="Mesa no encontrada")

    occupied_qty = (
        db.query(func.coalesce(func.sum(ProductLocationStock.quantity), 0))
        .filter(ProductLocationStock.location_id == loc.id, ProductLocationStock.quantity > 0)
        .scalar()
        or 0
    )
    if int(occupied_qty) > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"La mesa {loc.code} tiene {int(occupied_qty)} unidad(es) almacenadas. "
                "Reubica los productos desde el detalle de la mesa o mediante Putaway antes de eliminarla."
            ),
        )

    db.delete(loc)
    db.commit()


# ─── Zonas CRUD ───────────────────────────────────────────────────────────────

@router.post("/zones", response_model=LayoutZoneOut, status_code=status.HTTP_201_CREATED)
def create_zone(
    payload: ZoneCreateIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    ensure_default_layout(db)
    clean_code = payload.code.strip().upper()
    clean_name = payload.name.strip()
    if not clean_code or not clean_name:
        raise HTTPException(status_code=422, detail="Código y nombre de zona son obligatorios.")

    if db.query(WarehouseZone).filter(func.lower(WarehouseZone.code) == clean_code.lower()).first():
        raise HTTPException(status_code=409, detail=f"Ya existe una zona con código '{clean_code}'.")

    zone = WarehouseZone(
        code=clean_code,
        name=clean_name,
        color=(payload.color or "#6366f1").strip() or "#6366f1",
    )
    db.add(zone)
    db.flush()

    created_racks: List[LayoutLocationOut] = []
    seen_rack_codes = set()
    for raw_rack in payload.racks:
        r_code = raw_rack.strip().upper()
        if not r_code or r_code in seen_rack_codes:
            continue
        seen_rack_codes.add(r_code)
        if db.query(WarehouseLocation).filter(func.lower(WarehouseLocation.code) == r_code.lower()).first():
            db.rollback()
            raise HTTPException(status_code=409, detail=f"Ya existe una ubicación con código '{r_code}'.")
        rack = WarehouseLocation(
            code=r_code,
            name=f"Estantería {r_code}",
            location_type="rack",
            zone_id=zone.id,
        )
        db.add(rack)
        db.flush()
        created_racks.append(_serialize_location(rack, zone, {}, {}))

    db.commit()
    return LayoutZoneOut(
        id=zone.id,
        code=zone.code,
        name=zone.name,
        color=zone.color,
        racks=created_racks,
        total_units=0,
        occupied_racks_count=0,
    )


@router.put("/zones/{zone_id}", response_model=LayoutZoneOut)
def update_zone(
    zone_id: int,
    payload: ZoneUpdateIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    zone = db.query(WarehouseZone).filter(WarehouseZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    if payload.code is not None:
        clean_code = payload.code.strip().upper()
        if not clean_code:
            raise HTTPException(status_code=422, detail="El código de zona no puede quedar vacío.")
        dup = (
            db.query(WarehouseZone)
            .filter(func.lower(WarehouseZone.code) == clean_code.lower(), WarehouseZone.id != zone.id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"Ya existe otra zona con código '{clean_code}'.")
        zone.code = clean_code

    if payload.name is not None:
        clean_name = payload.name.strip()
        if clean_name:
            zone.name = clean_name

    if payload.color is not None and payload.color.strip():
        zone.color = payload.color.strip()

    db.commit()
    overview = get_warehouse_layout(db, _)
    return next(z for z in overview.zones if z.id == zone.id)


@router.delete("/zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    zone = db.query(WarehouseZone).filter(WarehouseZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    occupied_rows = (
        db.query(WarehouseLocation.code, func.sum(ProductLocationStock.quantity).label("qty"))
        .join(ProductLocationStock, ProductLocationStock.location_id == WarehouseLocation.id)
        .filter(WarehouseLocation.zone_id == zone.id, ProductLocationStock.quantity > 0)
        .group_by(WarehouseLocation.code)
        .all()
    )
    if occupied_rows:
        detail_list = ", ".join(f"{r.code} ({int(r.qty)} uds)" for r in occupied_rows)
        raise HTTPException(
            status_code=409,
            detail=f"No se puede eliminar la zona '{zone.code}' porque tiene estanterías ocupadas: {detail_list}.",
        )

    db.delete(zone)
    db.commit()


# ─── Estanterías (Racks) CRUD ─────────────────────────────────────────────────

@router.post("/zones/{zone_id}/racks", response_model=LayoutLocationOut, status_code=status.HTTP_201_CREATED)
def create_rack(
    zone_id: int,
    payload: RackCreateIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    zone = db.query(WarehouseZone).filter(WarehouseZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    clean_code = payload.code.strip().upper()
    if not clean_code:
        raise HTTPException(status_code=422, detail="El código de la estantería es requerido.")

    exists = db.query(WarehouseLocation).filter(func.lower(WarehouseLocation.code) == clean_code.lower()).first()
    if exists:
        raise HTTPException(status_code=409, detail=f"Ya existe una ubicación con código '{clean_code}'.")

    clean_name = (payload.name or "").strip() or f"Estantería {clean_code}"
    rack = WarehouseLocation(code=clean_code, name=clean_name, location_type="rack", zone_id=zone.id)
    db.add(rack)
    db.commit()
    db.refresh(rack)
    return _serialize_location(rack, zone, {}, {})


@router.put("/racks/{rack_id}", response_model=LayoutLocationOut)
def update_rack(
    rack_id: int,
    payload: RackUpdateIn,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    rack = db.query(WarehouseLocation).filter(WarehouseLocation.id == rack_id, WarehouseLocation.location_type == "rack").first()
    if not rack:
        raise HTTPException(status_code=404, detail="Estantería no encontrada")

    if payload.code is not None:
        clean_code = payload.code.strip().upper()
        if not clean_code:
            raise HTTPException(status_code=422, detail="El código de estantería no puede quedar vacío.")
        dup = (
            db.query(WarehouseLocation)
            .filter(func.lower(WarehouseLocation.code) == clean_code.lower(), WarehouseLocation.id != rack.id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"Ya existe otra ubicación con código '{clean_code}'.")
        rack.code = clean_code

    if payload.name is not None:
        clean_name = payload.name.strip()
        if clean_name:
            rack.name = clean_name

    db.flush()
    _sync_location_products_after_rename(rack.id, db)
    db.commit()
    return get_location_items(rack.id, db, _)


@router.delete("/racks/{rack_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rack(
    rack_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    rack = db.query(WarehouseLocation).filter(WarehouseLocation.id == rack_id, WarehouseLocation.location_type == "rack").first()
    if not rack:
        raise HTTPException(status_code=404, detail="Estantería no encontrada")

    occupied_qty = (
        db.query(func.coalesce(func.sum(ProductLocationStock.quantity), 0))
        .filter(ProductLocationStock.location_id == rack.id, ProductLocationStock.quantity > 0)
        .scalar()
        or 0
    )
    if int(occupied_qty) > 0:
        raise HTTPException(
            status_code=409,
            detail=f"La estantería {rack.code} tiene {int(occupied_qty)} unidad(es) almacenadas. Vacíala antes de eliminarla.",
        )

    db.delete(rack)
    db.commit()
