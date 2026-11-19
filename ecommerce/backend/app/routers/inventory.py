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
from app.models.work_order import WorkOrder, WorkOrderItem
from app.models.pending_reception import PendingReception
from app.routers.auth import get_current_user, require_admin, require_supervisor_or_admin
from app.schemas.inventory import (
    ProductCreate, ProductOut, ProductUpdate,
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

WAREHOUSE_LAYOUT_RACKS = [
    {"code": "A-01", "zone": "A", "label": "Zona A — Insumos (Rack A-01)"},
    {"code": "A-02", "zone": "A", "label": "Zona A — Insumos (Rack A-02)"},
    {"code": "A-03", "zone": "A", "label": "Zona A — Insumos (Rack A-03)"},
    {"code": "B-01", "zone": "B", "label": "Zona B — Electrónica (Rack B-01)"},
    {"code": "B-02", "zone": "B", "label": "Zona B — Electrónica (Rack B-02)"},
    {"code": "B-03", "zone": "B", "label": "Zona B — Electrónica (Rack B-03)"},
    {"code": "B-04", "zone": "B", "label": "Zona B — Electrónica (Rack B-04)"},
    {"code": "C-01", "zone": "C", "label": "Zona C — Periféricos (Rack C-01)"},
    {"code": "C-02", "zone": "C", "label": "Zona C — Periféricos (Rack C-02)"},
    {"code": "C-03", "zone": "C", "label": "Zona C — Periféricos (Rack C-03)"},
    {"code": "D-01", "zone": "D", "label": "Zona D — Cuarentena (Rack D-01)"},
    {"code": "D-02", "zone": "D", "label": "Zona D — Cuarentena (Rack D-02)"},
]
VALID_LOCATION_PATTERN = re.compile(r"^[ABCD](?:-\d{2}(?:-[A-Z0-9]+)?)?$")


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
        .where(WorkOrder.status.in_(["pending", "waiting_stock", "por_asignar", "assigned", "in_preparation", "in_progress"]))
        .group_by(WorkOrderItem.sku)
    ).all()
    for row in rows:
        reserved_by_sku[row.sku] = int(row.reserved)

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
        out = ProductOut.model_validate(p)
        out.reserved_qty  = reserved
        out.available_qty = max(0, p.stock_quantity - reserved)
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
    summary="Listar ubicaciones válidas del layout físico del almacén",
)
def list_warehouse_locations(
    _: object = Depends(get_current_user),
):
    """Retorna los racks del layout físico del almacén para asignación de Putaway."""
    return WAREHOUSE_LAYOUT_RACKS


@router.post(
    "/putaway",
    response_model=PutawayResponse,
    summary="Registrar almacenamiento (Putaway) y asignar ubicación a un producto",
)
def register_putaway(
    payload: PutawayRequest,
    db: Session = Depends(get_db),
    current_user: object = Depends(get_current_user),
):
    """
    Registra el almacenamiento físico (Putaway) de un SKU existente en una
    ubicación válida del almacén, actualizando su warehouse_location real.
    Valida existencia del SKU, formato de ubicación y stock físico suficiente.
    """
    clean_sku = payload.sku.strip()
    clean_location = payload.location.strip().upper()

    if not clean_sku:
        raise HTTPException(status_code=422, detail="El SKU es obligatorio.")

    if not VALID_LOCATION_PATTERN.match(clean_location):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Ubicación '{payload.location}' inválida. Usa una zona o rack del layout "
                "(ej: A-01, B-02, C-03, D-01)."
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

    if payload.quantity > product.stock_quantity:
        raise HTTPException(
            status_code=409,
            detail=(
                f"La cantidad a almacenar ({payload.quantity}) supera el stock físico "
                f"actual en bodega ({product.stock_quantity}) para {product.sku}."
            ),
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

    previous_location = product.warehouse_location
    product.warehouse_location = clean_location

    db.commit()
    db.refresh(product)

    user_email = getattr(current_user, "email", "usuario")
    logger.info(
        "📥 Putaway registrado por %s: SKU=%s qty=%d ubicacion %s -> %s",
        user_email, product.sku, payload.quantity, previous_location, clean_location,
    )

    return PutawayResponse(
        message=f"Putaway confirmado: {product.sku} x{payload.quantity} almacenado en {clean_location}.",
        sku=product.sku,
        product_name=product.product_name,
        quantity=payload.quantity,
        previous_location=previous_location,
        new_location=clean_location,
        stock_quantity=product.stock_quantity,
        reserved_qty=reserved_int,
        available_qty=available_int,
    )
