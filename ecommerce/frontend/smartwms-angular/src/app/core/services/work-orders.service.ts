// core/services/work-orders.service.ts
// Servicio Angular para el sistema de Pedidos de Bodega (Work Orders)

import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface WorkOrderItemOut {
  id: number;
  sku: string;
  product_name: string;
  quantity: number;
}

export interface WorkOrder {
  id: number;
  order_number: string;
  status: 'pending' | 'dispatched' | 'cancelled';
  created_by_email: string | null;
  assigned_operario_email: string | null;
  dispatched_by_email: string | null;
  created_at: string;
  dispatched_at: string | null;
  cancelled_at: string | null;
  items: WorkOrderItemOut[];
}

export interface Operario {
  id: number;
  email: string;
  full_name: string | null;
}

export interface WorkOrderItemIn {
  sku: string;
  quantity: number;
}

export interface WorkOrderCreate {
  items: WorkOrderItemIn[];
  assigned_operario_email?: string | null;
}

@Injectable({ providedIn: 'root' })
export class WorkOrdersService {
  private readonly baseUrl = `${environment.apiUrl}/api/v1/work-orders`;

  constructor(private http: HttpClient) {}

  /** Lista todos los pedidos, opcionalmente filtrados por status y/o por operario asignado */
  getWorkOrders(status?: string, assignedTo?: string): Observable<WorkOrder[]> {
    let params = new HttpParams();
    if (status) params = params.set('status', status);
    if (assignedTo) params = params.set('assigned_to', assignedTo);
    return this.http.get<WorkOrder[]>(this.baseUrl, { params });
  }

  /** Detalle de un pedido */
  getWorkOrder(id: number): Observable<WorkOrder> {
    return this.http.get<WorkOrder>(`${this.baseUrl}/${id}`);
  }

  /** Crear un pedido (supervisor) */
  createWorkOrder(payload: WorkOrderCreate): Observable<WorkOrder> {
    return this.http.post<WorkOrder>(this.baseUrl, payload);
  }

  /** Despachar un pedido (operario) */
  dispatch(id: number): Observable<WorkOrder> {
    return this.http.post<WorkOrder>(`${this.baseUrl}/${id}/dispatch`, {});
  }

  /** Cancelar un pedido (supervisor) */
  cancel(id: number): Observable<WorkOrder> {
    return this.http.post<WorkOrder>(`${this.baseUrl}/${id}/cancel`, {});
  }

  /** Lista operarios activos disponibles para asignar pedidos */
  getOperarios(): Observable<Operario[]> {
    return this.http.get<Operario[]>(`${this.baseUrl}/operarios`);
  }
}
