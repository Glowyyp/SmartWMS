"""
core/qr.py — Generación determinista de códigos QR en formato Data URI SVG para SKUs.
"""

from __future__ import annotations

import segno


def generate_sku_qr_data_uri(sku: str) -> str:
    """
    Genera un código QR estándar (no Micro QR) determinista y escaneable
    vinculado al SKU del producto.
    El contenido del QR es el SKU limpio para compatibilidad directa con ZXing y
    cualquier lector móvil estándar.
    """
    clean_sku = sku.strip()
    # make_qr fuerza QR estándar (micro=False) en vez de Micro QR, ya que ZXing y
    # la mayoría de lectores móviles no decodifican Micro QR en SKUs cortos.
    qr = segno.make_qr(clean_sku, error="M")
    return qr.svg_data_uri(scale=6, border=4, dark="#000000", light="#ffffff")
