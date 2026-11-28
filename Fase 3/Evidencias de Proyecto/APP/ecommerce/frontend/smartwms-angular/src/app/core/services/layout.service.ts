// core/services/layout.service.ts
// Servicio para administrar el Layout del Almacén (Mesas, Zonas, Estanterías y movimientos Putaway)

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface LocationItemDetail {
  sku: string;
  product_name: string;
  quantity: number;
  stored_at: string;
  stock_quantity: number;
  reserved_qty: number;
  available_qty: number;
  unit_price: number;
  reorder_point: number;
  is_low_stock: boolean;
}

export interface LayoutLocation {
  id: number;
  code: string;
  name: string;
  location_type: 'table' | 'rack';
  zone_id: number | null;
  zone_code: string | null;
  zone_name: string | null;
  occupied_skus_count: number;
  total_units: number;
  is_occupied: boolean;
  qr_code?: string | null;
  items: LocationItemDetail[];
}

export interface LayoutZone {
  id: number;
  code: string;
  name: string;
  color: string;
  racks: LayoutLocation[];
  total_units: number;
  occupied_racks_count: number;
}

export interface PutawayMovement {
  id: number;
  sku: string;
  product_name: string;
  quantity: number;
  source_location_code: string | null;
  destination_location_code: string;
  performed_by_email: string | null;
  notes: string | null;
  created_at: string;
}

export interface LayoutOverview {
  tables: LayoutLocation[];
  zones: LayoutZone[];
  movements: PutawayMovement[];
}

@Injectable({ providedIn: 'root' })
export class LayoutService {
  private readonly baseUrl = `${environment.apiUrl}/api/v1/layout`;

  constructor(private http: HttpClient) {}

  getLayout(): Observable<LayoutOverview> {
    return this.http.get<LayoutOverview>(this.baseUrl);
  }

  getLocationItems(locationId: number): Observable<LayoutLocation> {
    return this.http.get<LayoutLocation>(`${this.baseUrl}/locations/${locationId}/items`);
  }

  createTable(payload: { code: string; name?: string }): Observable<LayoutLocation> {
    return this.http.post<LayoutLocation>(`${this.baseUrl}/tables`, payload);
  }

  updateTable(tableId: number, payload: { code?: string; name?: string }): Observable<LayoutLocation> {
    return this.http.put<LayoutLocation>(`${this.baseUrl}/tables/${tableId}`, payload);
  }

  deleteTable(tableId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/tables/${tableId}`);
  }

  createZone(payload: { code: string; name: string; color: string; racks: string[] }): Observable<LayoutZone> {
    return this.http.post<LayoutZone>(`${this.baseUrl}/zones`, payload);
  }

  updateZone(zoneId: number, payload: { code?: string; name?: string; color?: string }): Observable<LayoutZone> {
    return this.http.put<LayoutZone>(`${this.baseUrl}/zones/${zoneId}`, payload);
  }

  deleteZone(zoneId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/zones/${zoneId}`);
  }

  createRack(zoneId: number, payload: { code: string; name?: string }): Observable<LayoutLocation> {
    return this.http.post<LayoutLocation>(`${this.baseUrl}/zones/${zoneId}/racks`, payload);
  }

  updateRack(rackId: number, payload: { code?: string; name?: string }): Observable<LayoutLocation> {
    return this.http.put<LayoutLocation>(`${this.baseUrl}/racks/${rackId}`, payload);
  }

  deleteRack(rackId: number): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/racks/${rackId}`);
  }
}
