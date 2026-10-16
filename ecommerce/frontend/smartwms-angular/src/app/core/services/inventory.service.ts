// core/services/inventory.service.ts
// Servicio para operaciones CRUD del inventario de productos

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface ProductInventory {
  id: number;
  sku: string;
  product_name: string;
  stock_quantity: number;   // Stock físico real
  unit_price: number;
  reorder_point: number;
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
  created_at: string;
  updated_at: string;
  reserved_qty: number;     // Unidades reservadas en pedidos pendientes
  available_qty: number;    // stock_quantity - reserved_qty
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

  confirmReception(id: number, received_quantity: number): Observable<PendingReception> {
    return this.http.post<PendingReception>(`${this.baseUrl}/receptions/${id}/confirm`, { received_quantity });
  }
}
