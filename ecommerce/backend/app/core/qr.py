"""
core/qr.py — Generación determinista de códigos QR en formato Data URI SVG para SKUs.
"""

from __future__ import annotations

import segno


def generate_sku_qr_data_uri(sku: str) -> str:
    """
    Genera un código QR determinista y escaneable vinculado al SKU del producto.
    El contenido del QR es el SKU limpio para compatibilidad directa con el escáner móvil.
    """
    clean_sku = sku.strip()
    qr = segno.make(clean_sku, error="M")
    return qr.svg_data_uri(scale=6, border=2, dark="#0f172a", light="#ffffff")
