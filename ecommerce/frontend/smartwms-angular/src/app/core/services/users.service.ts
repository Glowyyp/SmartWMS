// core/services/users.service.ts
// Servicio Angular para gestión de usuarios (supervisor/admin only)

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface UserRecord {
  id: number;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class UsersService {
  private readonly baseUrl = `${environment.apiUrl}/api/v1/users`;

  constructor(private http: HttpClient) {}

  getUsers(): Observable<UserRecord[]> {
    return this.http.get<UserRecord[]>(this.baseUrl);
  }

  getUser(id: number): Observable<UserRecord> {
    return this.http.get<UserRecord>(`${this.baseUrl}/${id}`);
  }

  toggleActive(id: number): Observable<UserRecord> {
    return this.http.patch<UserRecord>(`${this.baseUrl}/${id}/activate`, {});
  }
}
