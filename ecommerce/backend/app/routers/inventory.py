"""
routers/inventory.py — CRUD REST de Inventario

GET    /api/v1/inventory       → Listar productos (requiere JWT)
POST   /api/v1/inventory       → Agregar producto (requiere JWT admin)
PUT    /api/v1/inventory/{id}  → Editar producto   (requiere JWT admin)
DELETE /api/v1/inventory/{id}  → Eliminar producto (requiere JWT admin)
"""

from __future__ import annotations

import logging
import re
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.qr import generate_sku_qr_data_uri
from app.database import get_db
from app.models.inventory import ProductInventory
from app.models.warehouse import (
    ProductLocationStock,
    PutawayMovement,
    WarehouseLocation,
    WarehouseZone,
)
from app.models.work_order import WorkOrder, WorkOrderItem
from app.models.pending_reception import PendingReception
from app.routers.auth import get_current_user, require_admin, require_supervisor_or_admin
from app.services.layout_service import (
    ensure_default_layout,
    get_located_qty_by_sku,
    sync_product_warehouse_location_summary,
)
from app.schemas.inventory import (
    ProductCreate, ProductOut, ProductUpdate, ProductLocationBreakdown,
    PendingReceptionCreate, PendingReceptionOut, PendingReceptionConfirm, PendingReceptionUpdate,
    PutawayRequest, PutawayResponse,
)
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventario"])

ACTIVE_RESERVED_STATUSES = [
    "pending",
    "waiting_stock",
    "por_asignar",
    "assigned",
    "in_preparation",
    "in_progress",
]


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
    Incluye reserved_qty (suma de pedidos pendientes), available_qty y
    el desglose real por ubicación (location_stocks / unlocated_qty).
    """
    ensure_default_layout(db)
    products = db.query(ProductInventory).order_by(ProductInventory.sku).all()

    # Una sola query para obtener el total reservado por SKU
    reserved_by_sku: dict[str, int] = {}
    rows = db.execute(
        select(WorkOrderItem.sku, func.sum(WorkOrderItem.quantity).label("reserved"))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status.in_(ACTIVE_RESERVED_STATUSES))
        .group_by(WorkOrderItem.sku)
    ).all()
    for row in rows:
        reserved_by_sku[row.sku] = int(row.reserved)

    location_stocks_by_sku = get_located_qty_by_sku(db)

    dirty_qr = False
    for p in products:
        expected_qr = generate_sku_qr_data_uri(p.sku)
        if p.qr_code != expected_qr:
            p.qr_code = expected_qr
            dirty_qr = True
    if dirty_qr:
        db.commit()

    result = []
    for p in products:
        reserved = reserved_by_sku.get(p.sku, 0)
        loc_list = location_stocks_by_sku.get(p.sku, [])
        located_total = sum(x["quantity"] for x in loc_list)
        out = ProductOut.model_validate(p)
        out.reserved_qty = reserved
        out.available_qty = max(0, p.stock_quantity - reserved)
        out.location_stocks = [ProductLocationBreakdown(**x) for x in loc_list]
        out.unlocated_qty = max(0, p.stock_quantity - located_total)
        if out.estimated_volume is None and p.length and p.width and p.height:
            out.estimated_volume = p.length * p.width * p.height
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

    data = product_in.model_dump()
    if data.get("estimated_volume") is None and data.get("length") and data.get("width") and data.get("height"):
        data["estimated_volume"] = data["length"] * data["width"] * data["height"]
    data["qr_code"] = generate_sku_qr_data_uri(product_in.sku)

    product = ProductInventory(**data)
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

    # Recalcular volumen estimado si hay dimensiones disponibles
    l = getattr(product, "length", None)
    w = getattr(product, "width", None)
    h = getattr(product, "height", None)
    if l and w and h and ("estimated_volume" not in update_data or getattr(product, "estimated_volume", None) is None):
        product.estimated_volume = l * w * h

    expected_qr = generate_sku_qr_data_uri(product.sku)
    if product.qr_code != expected_qr:
        product.qr_code = expected_qr

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


# ─── PENDING RECEPTIONS ───────────────────────────────────────────────────────

@router.get(
    "/receptions",
    response_model=List[PendingReceptionOut],
    summary="Listar todas las recepciones pendientes o completadas",
)
def list_receptions(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    return db.query(PendingReception).order_by(PendingReception.created_at.desc()).all()


@router.post(
    "/receptions",
    response_model=PendingReceptionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un registro de stock pendiente (Supervisor/Admin)",
)
def create_pending_reception(
    reception_in: PendingReceptionCreate,
    db: Session = Depends(get_db),
    current_user: object = Depends(require_supervisor_or_admin),
):
    product = db.query(ProductInventory).filter(ProductInventory.sku == reception_in.sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    
    reception = PendingReception(**reception_in.model_dump())
    reception.created_by_id = current_user.id
    db.add(reception)
    
    # Actualizamos el pending_quantity del producto
    product.pending_quantity += reception.expected_quantity
    
    db.commit()
    db.refresh(reception)
    return reception


def _unlock_waiting_work_orders(db: Session) -> None:
    """Pasa pedidos 'waiting_stock' a 'pending'/'por_asignar' en orden FIFO si ya hay stock disponible."""
    waiting_orders = (
        db.query(WorkOrder)
        .filter(WorkOrder.status == "waiting_stock")
        .order_by(WorkOrder.created_at)
        .all()
    )

    for wo in waiting_orders:
        can_fulfill = True
        for item in wo.items:
            prod = db.query(ProductInventory).filter(ProductInventory.sku == item.sku).first()
            if not prod:
                can_fulfill = False
                break

            already_reserved_despachable = db.execute(
                select(func.sum(WorkOrderItem.quantity))
                .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
                .where(
                    WorkOrder.status.in_(["pending", "por_asignar", "in_preparation", "in_progress"]),
                    WorkOrderItem.sku == prod.sku,
                )
            ).scalar() or 0

            if (prod.stock_quantity - already_reserved_despachable) < item.quantity:
                can_fulfill = False
                break

        if can_fulfill:
            wo.status = "pending" if (wo.assigned_operario_id is not None or wo.assigned_operario_email) else "por_asignar"


@router.post(
    "/receptions/{reception_id}/confirm",
    response_model=PendingReceptionOut,
    summary="Confirmar recepción total o parcial de stock (Supervisor/Admin)",
)
def confirm_pending_reception(
    reception_id: int,
    confirm_in: PendingReceptionConfirm,
    db: Session = Depends(get_db),
    current_user: object = Depends(require_supervisor_or_admin),
):
    reception = db.query(PendingReception).filter(PendingReception.id == reception_id).first()
    if not reception:
        raise HTTPException(status_code=404, detail="Recepción no encontrada")
    if reception.status in ["completed", "cancelled"]:
        raise HTTPException(status_code=400, detail=f"La recepción ya está {reception.status}")

    product = db.query(ProductInventory).filter(ProductInventory.sku == reception.sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado (pudo haber sido borrado)")

    added_to_received = confirm_in.received_quantity

    if reception.status == "pending":
        # Si la recepción aún estaba pendiente (pudo haberse pre-editado received_quantity
        # como borrador en Editar), al confirmar se acredita added_to_received una sola vez.
        remaining_before = reception.expected_quantity
        reception.received_quantity = added_to_received
    else:
        # Si ya estaba en estado 'partial', esta confirmación suma una nueva entrega adicional.
        remaining_before = max(0, reception.expected_quantity - reception.received_quantity)
        reception.received_quantity += added_to_received

    reception.received_by_id = current_user.id
    reception.received_at = datetime.now(timezone.utc)
    if confirm_in.notes is not None:
        reception.notes = confirm_in.notes.strip() or None

    if confirm_in.close_shortage or reception.received_quantity >= reception.expected_quantity:
        reception.status = "completed"
        # Libera toda la cantidad pendiente restante (ej. unidades dañadas o faltantes cerradas)
        pending_delta = remaining_before
    else:
        reception.status = "partial" if reception.received_quantity > 0 else "pending"
        pending_delta = min(remaining_before, added_to_received)

    # Actualizar inventario físico y por llegar
    product.stock_quantity += added_to_received
    product.pending_quantity = max(0, product.pending_quantity - pending_delta)

    db.commit()
    _unlock_waiting_work_orders(db)
    db.commit()
    db.refresh(reception)
    return reception


@router.put(
    "/receptions/{reception_id}",
    response_model=PendingReceptionOut,
    summary="Editar cantidades o notas de una recepción (Supervisor/Admin)",
)
def update_pending_reception(
    reception_id: int,
    payload: PendingReceptionUpdate,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    """
    Permite corregir la cantidad esperada, cantidad recibida real y notas de una recepción.
    - Si está en estado 'pending', guarda received_quantity y notes como valores preparados
      para que al presionar 'Confirmar' ya aparezcan precargados sin acreditar stock doble.
    - Si está en 'partial' o 'completed', ajusta el stock_quantity físico por la diferencia.
    """
    reception = db.query(PendingReception).filter(PendingReception.id == reception_id).first()
    if not reception:
        raise HTTPException(status_code=404, detail="Recepción no encontrada")
    if reception.status == "cancelled":
        raise HTTPException(status_code=400, detail="No se puede editar una recepción cancelada")

    product = db.query(ProductInventory).filter(ProductInventory.sku == reception.sku).first()
    if not product:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    old_expected = reception.expected_quantity
    old_received = reception.received_quantity
    new_expected = payload.expected_quantity if payload.expected_quantity is not None else old_expected
    new_received = payload.received_quantity if payload.received_quantity is not None else old_received

    if payload.notes is not None:
        reception.notes = payload.notes.strip() or None

    if reception.status == "pending":
        reception.expected_quantity = new_expected
        reception.received_quantity = new_received
        product.pending_quantity = max(0, product.pending_quantity + (new_expected - old_expected))
        db.commit()
        db.refresh(reception)
        return reception

    old_remaining = 0 if reception.status in ["completed", "cancelled"] else max(0, old_expected - old_received)
    delta_received = new_received - old_received

    if product.stock_quantity + delta_received < 0:
        raise HTTPException(
            status_code=409,
            detail="No se puede reducir la cantidad recibida porque el stock físico quedaría negativo",
        )

    reception.expected_quantity = new_expected
    reception.received_quantity = new_received

    if new_received >= new_expected:
        reception.status = "completed"
    elif new_received > 0:
        reception.status = "partial"
    else:
        reception.status = "pending"

    new_remaining = 0 if reception.status in ["completed", "pending"] else max(0, new_expected - new_received)
    if reception.status == "pending":
        new_remaining = new_expected

    product.stock_quantity += delta_received
    product.pending_quantity = max(0, product.pending_quantity + (new_remaining - old_remaining))

    db.commit()
    if delta_received > 0:
        _unlock_waiting_work_orders(db)
        db.commit()
    db.refresh(reception)
    return reception


@router.post(
    "/receptions/{reception_id}/cancel",
    response_model=PendingReceptionOut,
    summary="Cancelar una recepción pendiente o parcial (Supervisor/Admin)",
)
def cancel_pending_reception(
    reception_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(require_supervisor_or_admin),
):
    """Cancela la recepción y libera de pending_quantity las unidades que aún no habían llegado."""
    reception = db.query(PendingReception).filter(PendingReception.id == reception_id).first()
    if not reception:
        raise HTTPException(status_code=404, detail="Recepción no encontrada")
    if reception.status == "completed":
        raise HTTPException(status_code=400, detail="No se puede cancelar una recepción ya completada")
    if reception.status == "cancelled":
        raise HTTPException(status_code=400, detail="La recepción ya se encuentra cancelada")

    product = db.query(ProductInventory).filter(ProductInventory.sku == reception.sku).first()
    remaining_pending = (
        reception.expected_quantity
        if reception.status == "pending"
        else max(0, reception.expected_quantity - reception.received_quantity)
    )
    reception.status = "cancelled"

    if product:
        product.pending_quantity = max(0, product.pending_quantity - remaining_pending)

    db.commit()
    db.refresh(reception)
    return reception


# ─── PUTAWAY (Ubicación de productos en bodega) ────────────────────────────────

@router.get(
    "/locations",
    summary="Listar ubicaciones dinámicas (zonas/estanterías y mesas) registradas en el Layout",
)
def list_warehouse_locations(
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
):
    """
    Retorna todas las ubicaciones activas configuradas en el Layout del Supervisor
    (estanterías de cada zona y mesas de bodega) con su ocupación actual.
    """
    ensure_default_layout(db)
    locs = (
        db.query(WarehouseLocation, WarehouseZone)
        .outerjoin(WarehouseZone, WarehouseZone.id == WarehouseLocation.zone_id)
        .order_by(WarehouseLocation.location_type.asc(), WarehouseLocation.code.asc())
        .all()
    )
    totals_rows = (
        db.query(
            ProductLocationStock.location_id,
            func.coalesce(func.sum(ProductLocationStock.quantity), 0).label("units"),
        )
        .filter(ProductLocationStock.quantity > 0)
        .group_by(ProductLocationStock.location_id)
        .all()
    )
    units_by_loc = {r.location_id: int(r.units) for r in totals_rows}

    result = []
    for loc, zone in locs:
        total_units = units_by_loc.get(loc.id, 0)
        if loc.location_type == "table":
            label = f"Mesa {loc.code} — {loc.name}"
        else:
            zone_label = zone.name if zone else (loc.name or loc.code)
            label = f"{zone_label} ({loc.code})"
        result.append({
            "id": loc.id,
            "code": loc.code,
            "name": loc.name,
            "location_type": loc.location_type,
            "zone_code": zone.code if zone else None,
            "zone_name": zone.name if zone else None,
            "zone": zone.code if zone else "MESA",
            "label": label,
            "total_units": total_units,
            "is_occupied": total_units > 0,
        })
    return result


@router.post(
    "/putaway",
    response_model=PutawayResponse,
    summary="Registrar almacenamiento o traslado (Putaway) conectado al Layout real",
)
def register_putaway(
    payload: PutawayRequest,
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """
    Almacena stock sin ubicar o traslada stock desde una ubicación origen hacia
    una ubicación destino válida registrada en el Layout (mesa o estantería),
    sin duplicar ni alterar el stock_quantity total del producto.
    """
    ensure_default_layout(db)

    clean_sku = payload.sku.strip()
    clean_dest = payload.location.strip().upper()
    clean_source = (payload.source_location or "").strip().upper() or None

    if not clean_sku:
        raise HTTPException(status_code=422, detail="El SKU es obligatorio.")

    dest_loc = (
        db.query(WarehouseLocation)
        .filter(func.lower(WarehouseLocation.code) == clean_dest.lower())
        .first()
    )
    if not dest_loc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"La ubicación de destino '{payload.location}' no existe en el Layout "
                "o fue eliminada por el supervisor."
            ),
        )

    product = db.execute(
        select(ProductInventory)
        .where(func.lower(ProductInventory.sku) == clean_sku.lower())
        .with_for_update()
    ).scalar_one_or_none()

    if not product:
        raise HTTPException(
            status_code=404,
            detail=f"El SKU '{clean_sku}' no existe en el inventario.",
        )

    if product.stock_quantity <= 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"El producto {product.sku} ({product.product_name}) no tiene stock físico "
                "en bodega (stock = 0). Registra o confirma una recepción primero."
            ),
        )

    previous_location_summary = product.warehouse_location

    if clean_source:
        if clean_source == dest_loc.code.upper():
            raise HTTPException(
                status_code=422,
                detail=f"La ubicación origen y destino no pueden ser iguales ({dest_loc.code}).",
            )
        source_loc = (
            db.query(WarehouseLocation)
            .filter(func.lower(WarehouseLocation.code) == clean_source.lower())
            .first()
        )
        if not source_loc:
            raise HTTPException(
                status_code=404,
                detail=f"La ubicación de origen '{clean_source}' no existe en el Layout.",
            )
        source_stock = db.execute(
            select(ProductLocationStock)
            .where(
                ProductLocationStock.sku == product.sku,
                ProductLocationStock.location_id == source_loc.id,
            )
            .with_for_update()
        ).scalar_one_or_none()

        available_at_source = source_stock.quantity if source_stock else 0
        if payload.quantity > available_at_source:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Stock insuficiente en {source_loc.code}: intentas mover {payload.quantity} uds "
                    f"de {product.sku}, pero solo hay {available_at_source} uds en esa ubicación."
                ),
            )

        source_stock.quantity -= payload.quantity
        if source_stock.quantity == 0:
            db.delete(source_stock)
        effective_source_code = source_loc.code
    else:
        located_total = int(
            db.execute(
                select(func.coalesce(func.sum(ProductLocationStock.quantity), 0))
                .where(ProductLocationStock.sku == product.sku)
            ).scalar()
            or 0
        )
        unlocated_qty = max(0, product.stock_quantity - located_total)
        if payload.quantity > unlocated_qty:
            existing_rows = get_located_qty_by_sku(db, [product.sku]).get(product.sku, [])
            if existing_rows:
                locs_desc = ", ".join(f"{r['location_code']} ({r['quantity']})" for r in existing_rows)
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Solo quedan {unlocated_qty} unidad(es) sin ubicar de {product.sku} "
                        f"(stock físico total: {product.stock_quantity}; ubicadas en: {locs_desc}). "
                        "Selecciona una ubicación de origen para mover stock sin duplicarlo."
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    f"La cantidad a almacenar ({payload.quantity}) supera el stock físico "
                    f"disponible ({product.stock_quantity}) para {product.sku}."
                ),
            )
        effective_source_code = None

    dest_stock = db.execute(
        select(ProductLocationStock)
        .where(
            ProductLocationStock.sku == product.sku,
            ProductLocationStock.location_id == dest_loc.id,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if dest_stock is None:
        dest_stock = ProductLocationStock(
            product_id=product.id,
            sku=product.sku,
            location_id=dest_loc.id,
            quantity=payload.quantity,
        )
        db.add(dest_stock)
    else:
        dest_stock.quantity += payload.quantity

    db.flush()
    sync_product_warehouse_location_summary(product, db)

    user_id = getattr(current_user, "id", None)
    user_email = getattr(current_user, "email", "usuario")
    db.add(
        PutawayMovement(
            sku=product.sku,
            product_name=product.product_name,
            quantity=payload.quantity,
            source_location_code=effective_source_code,
            destination_location_code=dest_loc.code,
            performed_by_id=user_id,
            performed_by_email=user_email,
            notes=(payload.notes or "").strip() or None,
        )
    )

    reserved = db.execute(
        select(func.sum(WorkOrderItem.quantity))
        .join(WorkOrder, WorkOrder.id == WorkOrderItem.work_order_id)
        .where(
            WorkOrder.status.in_(ACTIVE_RESERVED_STATUSES),
            WorkOrderItem.sku == product.sku,
        )
    ).scalar() or 0
    reserved_int = int(reserved)
    available_int = max(0, product.stock_quantity - reserved_int)

    db.commit()
    db.refresh(product)
    db.refresh(dest_stock)

    loc_breakdown = get_located_qty_by_sku(db, [product.sku]).get(product.sku, [])
    located_after = sum(x["quantity"] for x in loc_breakdown)
    unlocated_after = max(0, product.stock_quantity - located_after)

    logger.info(
        "📥 Putaway registrado por %s: SKU=%s qty=%d %s -> %s",
        user_email, product.sku, payload.quantity, effective_source_code or "Sin ubicar", dest_loc.code,
    )

    action_label = f"Movido desde {effective_source_code} hacia {dest_loc.code}" if effective_source_code else f"Almacenado en {dest_loc.code}"
    return PutawayResponse(
        message=f"Putaway confirmado: {product.sku} x{payload.quantity} ({action_label}).",
        sku=product.sku,
        product_name=product.product_name,
        quantity=payload.quantity,
        previous_location=previous_location_summary,
        source_location=effective_source_code,
        new_location=dest_loc.code,
        location_total_quantity=dest_stock.quantity,
        stock_quantity=product.stock_quantity,
        reserved_qty=reserved_int,
        available_qty=available_int,
        unlocated_qty=unlocated_after,
        location_stocks=[ProductLocationBreakdown(**x) for x in loc_breakdown],
    )
