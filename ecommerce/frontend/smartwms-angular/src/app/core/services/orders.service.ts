// core/services/orders.service.ts
// Servicio Angular para consultar órdenes desde el backend (GET /api/v1/orders)

import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface OrderItem {
  id: number;
  sku: string;
  quantity: number;
  unit_price: number;
  subtotal: number;
}

export interface Order {
  id: number;
  external_order_id: string;
  customer_id: string;
  customer_name: string;
  customer_email: string;
  total: number;
  status: string; // received | processing | completed | failed | cancelled
  received_at: string;
  event_timestamp: string;
  items: OrderItem[];
}

@Injectable({ providedIn: 'root' })
export class OrdersService {
  private readonly baseUrl = `${environment.apiUrl}/api/v1/orders`;

  constructor(private http: HttpClient) {}

  /**
   * Lista órdenes, opcionalmente filtradas por status.
   * @param status  'received' | 'processing' | 'completed' | 'failed' | undefined
   * @param limit   Máximo de registros (default 50)
   */
  getOrders(status?: string, limit = 50): Observable<Order[]> {
    let params = new HttpParams().set('limit', limit);
    if (status) params = params.set('status', status);
    return this.http.get<Order[]>(this.baseUrl, { params });
  }

  getOrder(id: number): Observable<Order> {
    return this.http.get<Order>(`${this.baseUrl}/${id}`);
  }
}
