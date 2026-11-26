"""
models/warehouse.py — Modelos ORM para el Layout del Almacén y Stock por Ubicación

Tablas:
  - warehouse_zones: Zonas configurables (ej. A, B, C, D...)
  - warehouse_locations: Estanterías ('rack') dentro de zonas y Mesas ('table')
  - product_location_stocks: Cantidad real almacenada de cada SKU por ubicación
  - putaway_movements: Trazabilidad de movimientos Putaway (origen -> destino)
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class WarehouseZone(Base):
    __tablename__ = "warehouse_zones"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    color = Column(String(20), nullable=False, default="#6366f1")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    locations = relationship(
        "WarehouseLocation",
        back_populates="zone",
        cascade="all, delete-orphan",
        order_by="WarehouseLocation.code",
    )


class WarehouseLocation(Base):
    __tablename__ = "warehouse_locations"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    # 'rack' (estantería dentro de una zona) | 'table' (mesa de bodega)
    location_type = Column(String(20), nullable=False, default="rack", index=True)
    zone_id = Column(Integer, ForeignKey("warehouse_zones.id", ondelete="CASCADE"), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    zone = relationship("WarehouseZone", back_populates="locations")
    stock_items = relationship(
        "ProductLocationStock",
        back_populates="location",
        cascade="all, delete-orphan",
    )


class ProductLocationStock(Base):
    __tablename__ = "product_location_stocks"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="chk_location_stock_non_negative"),
        UniqueConstraint("sku", "location_id", name="uq_sku_location"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("product_inventory.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(100), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("warehouse_locations.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=0)

    stored_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    location = relationship("WarehouseLocation", back_populates="stock_items")


class PutawayMovement(Base):
    __tablename__ = "putaway_movements"

    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(100), nullable=False, index=True)
    product_name = Column(String(300), nullable=False)
    quantity = Column(Integer, nullable=False)
    source_location_code = Column(String(50), nullable=True)
    destination_location_code = Column(String(50), nullable=False)
    performed_by_id = Column(Integer, nullable=True)
    performed_by_email = Column(String(254), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
