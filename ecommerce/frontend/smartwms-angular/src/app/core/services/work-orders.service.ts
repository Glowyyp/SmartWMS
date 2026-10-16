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
  unit_price?: number | null;
  subtotal?: number | null;
}

export interface WorkOrderPackage {
  id: number;
  length: number | null;
  width: number | null;
  height: number | null;
  weight: number | null;
  created_at: string;
}

export interface WorkOrder {
  id: number;
  order_number: string;
  status: 'por_asignar' | 'waiting_stock' | 'pending' | 'assigned' | 'in_preparation' | 'in_progress' | 'dispatched' | 'cancelled' | string;
  created_by_id?: number | null;
  created_by_email: string | null;
  assigned_operario_id?: number | null;
  assigned_operario_email: string | null;
  dispatched_by_id?: number | null;
  dispatched_by_email: string | null;
  created_at: string;
  dispatched_at: string | null;
  cancelled_at: string | null;
  total_weight: number | null;
  total_volume: number | null;
  packages_count: number;
  total_items?: number;
  total_amount?: number;
  items: WorkOrderItemOut[];
  packages: WorkOrderPackage[];
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
  assigned_operario_id?: number | null;
  assigned_operario_email?: string | null;
}

export interface WorkOrderUpdate {
  status?: string | null;
  assigned_operario_id?: number | null;
  assigned_operario_email?: string | null;
  items?: WorkOrderItemIn[];
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

  /** Editar un pedido completo (supervisor) */
  updateWorkOrder(id: number, payload: WorkOrderUpdate): Observable<WorkOrder> {
    return this.http.put<WorkOrder>(`${this.baseUrl}/${id}`, payload);
  }

  /** Despachar un pedido (operario) */
  dispatch(id: number, payload?: any): Observable<WorkOrder> {
    return this.http.post<WorkOrder>(`${this.baseUrl}/${id}/dispatch`, payload || {});
  }

  /** Cancelar un pedido (supervisor) */
  cancel(id: number): Observable<WorkOrder> {
    return this.http.post<WorkOrder>(`${this.baseUrl}/${id}/cancel`, {});
  }

  /** Asignar un pedido a un operario */
  assignWorkOrder(id: number, assigned_operario_id: number | null, assigned_operario_email: string | null): Observable<WorkOrder> {
    return this.http.put<WorkOrder>(`${this.baseUrl}/${id}/assign`, {
      assigned_operario_id,
      assigned_operario_email
    });
  }

  /** Lista operarios activos disponibles para asignar pedidos */
  getOperarios(): Observable<Operario[]> {
    return this.http.get<Operario[]>(`${this.baseUrl}/operarios`);
  }
}
