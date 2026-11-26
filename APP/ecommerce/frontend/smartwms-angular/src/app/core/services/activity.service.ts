// core/services/activity.service.ts
// Servicio Angular para el módulo de Registro de Actividad y Métricas de Usuarios (Supervisor/Admin)

import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface SessionLog {
  id: number;
  user_id: number;
  user_name: string;
  role: string;
  client_type: string;
  started_at: string;
  last_activity_at: string;
  ended_at: string | null;
  duration_seconds: number;
  status: 'active' | 'closed' | 'timeout' | string;
  disconnect_reason: string | null;
  is_online: boolean;
}

export interface DailyActivityPoint {
  date: string;
  label: string;
  duration_seconds: number;
  sessions_count: number;
  active_users_count: number;
}

export interface UserActivitySummary {
  user_id: number;
  user_name: string;
  full_name: string | null;
  email: string | null;
  role: string;
  is_active: boolean;
  is_online: boolean;
  total_sessions: number;
  total_duration_seconds: number;
  avg_session_seconds: number;
  today_duration_seconds: number;
  week_duration_seconds: number;
  sessions_last_7_days: number;
  sessions_last_30_days: number;
  active_days_last_30_days: number;
  avg_sessions_per_active_day: number;
  frequency_label: string;
  last_login_at: string | null;
  last_activity_at: string | null;
  last_client_type: string | null;
}

export interface ActivityOverviewSummary {
  total_users: number;
  online_users: number;
  offline_users: number;
  active_sessions_count: number;
  total_sessions_count: number;
  total_usage_seconds: number;
  period_usage_seconds: number;
  session_timeout_seconds: number;
}

export interface ActivityOverview {
  summary: ActivityOverviewSummary;
  users: UserActivitySummary[];
  daily_activity: DailyActivityPoint[];
  recent_activity: SessionLog[];
}

export interface UserActivityDetail {
  user: UserActivitySummary;
  daily_activity: DailyActivityPoint[];
  sessions: SessionLog[];
}

export function formatDuration(totalSeconds: number | null | undefined): string {
  const secs = Math.max(0, Math.floor(Number(totalSeconds || 0)));
  if (secs === 0) return '0s';
  const days = Math.floor(secs / 86400);
  const hours = Math.floor((secs % 86400) / 3600);
  const minutes = Math.floor((secs % 3600) / 60);
  const remSecs = secs % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  if (minutes > 0) return remSecs > 0 ? `${minutes}m ${remSecs}s` : `${minutes}m`;
  return `${remSecs}s`;
}

export function formatCompactDuration(totalSeconds: number | null | undefined): string {
  const secs = Math.max(0, Math.floor(Number(totalSeconds || 0)));
  if (secs === 0) return '0m';
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  const hrs = secs / 3600;
  return `${hrs.toFixed(1)}h`;
}

@Injectable({ providedIn: 'root' })
export class ActivityService {
  private readonly baseUrl = `${environment.apiUrl}/api/v1/activity`;

  constructor(private http: HttpClient) {}

  getOverview(days = 7): Observable<ActivityOverview> {
    const params = new HttpParams().set('days', String(days));
    return this.http.get<ActivityOverview>(`${this.baseUrl}/overview`, { params });
  }

  getUserDetail(userId: number, days = 14, limit = 50): Observable<UserActivityDetail> {
    const params = new HttpParams()
      .set('days', String(days))
      .set('limit', String(limit));
    return this.http.get<UserActivityDetail>(`${this.baseUrl}/users/${userId}`, { params });
  }

  getSessions(options?: { userId?: number; status?: string; limit?: number }): Observable<SessionLog[]> {
    let params = new HttpParams();
    if (options?.userId !== undefined) params = params.set('user_id', String(options.userId));
    if (options?.status) params = params.set('status', options.status);
    if (options?.limit) params = params.set('limit', String(options.limit));
    return this.http.get<SessionLog[]>(`${this.baseUrl}/sessions`, { params });
  }
}
