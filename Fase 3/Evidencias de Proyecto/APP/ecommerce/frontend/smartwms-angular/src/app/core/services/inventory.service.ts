// core/services/inventory.service.ts
// Servicio para operaciones CRUD del inventario de productos

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface ProductLocationBreakdown {
  location_id: number;
  location_code: string;
  location_name: string;
  location_type: 'table' | 'rack';
  zone_code: string | null;
  quantity: number;
  stored_at: string;
}

export type StockStatus = 'healthy' | 'warning' | 'critical';

export interface ProductInventory {
  id: number;
  sku: string;
  product_name: string;
  stock_quantity: number;   // Stock físico real
  unit_price: number;
  reorder_point: number;
  warning_threshold?: number;
  stock_status?: StockStatus;
  is_low_stock: boolean;
  warehouse_location: string | null;  // Zona física en el almacén (A, B, C, D, etc.)
  pending_quantity: number;
  length: number | null;
  width: number | null;
  height: number | null;
  dimensions_unit: string;
  weight: number | null;
  weight_unit: string;
  has_box: boolean;
  qr_code?: string | null;
  created_at: string;
  updated_at: string;
  reserved_qty: number;     // Unidades reservadas en pedidos pendientes
  available_qty: number;    // stock_quantity - reserved_qty
  unlocated_qty?: number;
  location_stocks?: ProductLocationBreakdown[];
}

/**
 * Clasificación canónica de stock en 3 niveles (sincronizada con el backend):
 *  - 'critical' (Rojo — Crítico):      disponible <= 0 o disponible <= reorder_point
 *  - 'warning'  (Amarillo — Advertencia): reorder_point < disponible <= reorder_point * 2
 *  - 'healthy'  (Verde — Saludable):   disponible > reorder_point * 2 (y > 0)
 */
export function resolveStockStatus(product: Pick<ProductInventory, 'available_qty' | 'stock_quantity' | 'reorder_point' | 'stock_status'>): StockStatus {
  const qty = Math.max(0, Number(product.available_qty ?? product.stock_quantity ?? 0));
  const rp = Math.max(0, Number(product.reorder_point ?? 0));
  if (qty <= 0 || qty <= rp) return 'critical';
  if (rp > 0 && qty <= rp * 2) return 'warning';
  return 'healthy';
}

export function getStockStatusLabel(status: StockStatus): string {
  switch (status) {
    case 'critical':
      return 'Crítico';
    case 'warning':
      return 'Advertencia';
    default:
      return 'Saludable';
  }
}

export function getStockStatusChipClass(status: StockStatus): string {
  switch (status) {
    case 'critical':
      return 'chip-danger';
    case 'warning':
      return 'chip-warning';
    default:
      return 'chip-success';
  }
}

export interface PendingReception {
  id: number;
  sku: string;
  expected_quantity: number;
  received_quantity: number;
  expected_date: string | null;
  status: 'pending' | 'partial' | 'completed' | 'cancelled';
  notes: string | null;
  created_at: string;
  updated_at: string;
  received_at: string | null;
}

@Injectable({ providedIn: 'root' })
export class InventoryService {
  private readonly baseUrl = `${environment.apiUrl}/api/v1/inventory`;

  constructor(private http: HttpClient) {}

  /** Retorna el array de productos directamente (el backend no pagina) */
  getProducts(): Observable<ProductInventory[]> {
    return this.http.get<ProductInventory[]>(this.baseUrl);
  }

  getProduct(id: number): Observable<ProductInventory> {
    return this.http.get<ProductInventory>(`${this.baseUrl}/${id}`);
  }

  createProduct(data: Partial<ProductInventory>): Observable<ProductInventory> {
    return this.http.post<ProductInventory>(this.baseUrl, data);
  }

  updateProduct(id: number, data: Partial<ProductInventory>): Observable<ProductInventory> {
    return this.http.put<ProductInventory>(`${this.baseUrl}/${id}`, data);
  }

  deleteProduct(id: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/${id}`);
  }

  // --- Recepciones Pendientes ---
  getReceptions(): Observable<PendingReception[]> {
    return this.http.get<PendingReception[]>(`${this.baseUrl}/receptions`);
  }

  createReception(data: any): Observable<PendingReception> {
    return this.http.post<PendingReception>(`${this.baseUrl}/receptions`, data);
  }

  confirmReception(
    id: number,
    received_quantity: number,
    close_shortage = false,
    notes?: string | null
  ): Observable<PendingReception> {
    const body: { received_quantity: number; close_shortage: boolean; notes?: string } = {
      received_quantity,
      close_shortage,
    };
    if (notes !== undefined && notes !== null) body.notes = notes;
    return this.http.post<PendingReception>(`${this.baseUrl}/receptions/${id}/confirm`, body);
  }

  updateReception(
    id: number,
    payload: { expected_quantity?: number; received_quantity?: number; notes?: string | null }
  ): Observable<PendingReception> {
    return this.http.put<PendingReception>(`${this.baseUrl}/receptions/${id}`, payload);
  }

  cancelReception(id: number): Observable<PendingReception> {
    return this.http.post<PendingReception>(`${this.baseUrl}/receptions/${id}/cancel`, {});
  }

  registerPutaway(payload: {
    sku: string;
    quantity: number;
    location: string;
    source_location?: string | null;
    notes?: string | null;
  }): Observable<any> {
    return this.http.post(`${this.baseUrl}/putaway`, payload);
  }
}
