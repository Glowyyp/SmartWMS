// core/services/auth.service.ts
// Servicio de autenticación con soporte para MFA (TOTP), tokens seguros y guards

import { Injectable, signal, computed } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Router } from '@angular/router';
import { tap } from 'rxjs/operators';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface LoginPayload {
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token?: string | null;
  token_type?: string;
  role: string;
  mfa_required?: boolean;
  mfa_token?: string | null;
  stage?: 'verify' | 'setup' | null;
}

export interface MFASetupResponse {
  secret: string;
  provisioning_uri: string;
  qr_code_svg: string;
  recovery_codes: string[];
  issuer: string;
  account_name: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'smartwms_token';
  private readonly ROLE_KEY  = 'smartwms_role';
  private readonly HEARTBEAT_INTERVAL_MS = 25_000;
  private readonly IDLE_CUTOFF_MS = 5 * 60 * 1000; // 5 min sin interacción pausa el heartbeat

  // Signal reactivo para el estado de autenticación
  private _isAuth = signal<boolean>(this.hasValidToken());
  readonly isAuth = computed(() => this._isAuth());

  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private lastUserInteractionMs = Date.now();
  private wasIdlePaused = false;
  private interactionListenersAttached = false;

  private readonly onUserInteraction = (): void => {
    const now = Date.now();
    if (now - this.lastUserInteractionMs < 5000) return;
    this.lastUserInteractionMs = now;
    if (this.wasIdlePaused && this.hasValidToken()) {
      this.wasIdlePaused = false;
      this.sendHeartbeat();
    }
  };

  constructor(private http: HttpClient, private router: Router) {
    if (this.hasValidToken()) {
      this.startHeartbeat();
    }
  }

  /**
   * Paso 1: Envía credenciales al backend.
   * Si mfa_required es true, NO almacena sesión (espera segundo factor).
   */
  login(credentials: LoginPayload): Observable<AuthResponse> {
    const formData = new FormData();
    formData.append('username', credentials.email.trim());
    formData.append('password', credentials.password);

    return this.http
      .post<AuthResponse>(`${environment.apiUrl}/api/auth/login`, formData)
      .pipe(
        tap((response) => {
          if (!response.mfa_required && response.access_token) {
            this.saveFinalSession(response);
          }
        })
      );
  }

  /**
   * Paso 2A: Verificar código de 6 dígitos del autenticador (TOTP).
   */
  mfaVerify(code: string, mfaToken: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${environment.apiUrl}/api/auth/mfa/verify`, {
        code: code.trim(),
        mfa_token: mfaToken,
      })
      .pipe(tap((response) => this.saveFinalSession(response)));
  }

  /**
   * Paso 2B: Iniciar enrolamiento de autenticador (obtener QR, secreto y recovery codes).
   */
  mfaSetup(mfaToken: string): Observable<MFASetupResponse> {
    const headers = new HttpHeaders({ Authorization: `Bearer ${mfaToken}` });
    return this.http.post<MFASetupResponse>(
      `${environment.apiUrl}/api/auth/mfa/setup`,
      { body_token: mfaToken },
      { headers }
    );
  }

  /**
   * Paso 2C: Confirmar código inicial y activar MFA definitivamente en la cuenta.
   */
  mfaActivate(code: string, mfaToken: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${environment.apiUrl}/api/auth/mfa/activate`, {
        code: code.trim(),
        mfa_token: mfaToken,
      })
      .pipe(tap((response) => this.saveFinalSession(response)));
  }

  /**
   * Paso 2D: Acceso de emergencia con código de recuperación de un solo uso.
   */
  mfaRecover(recoveryCode: string, mfaToken: string): Observable<AuthResponse> {
    return this.http
      .post<AuthResponse>(`${environment.apiUrl}/api/auth/mfa/recover`, {
        recovery_code: recoveryCode.trim(),
        mfa_token: mfaToken,
      })
      .pipe(tap((response) => this.saveFinalSession(response)));
  }

  private saveFinalSession(response: AuthResponse): void {
    if (response.access_token) {
      localStorage.setItem(this.TOKEN_KEY, response.access_token);
      localStorage.setItem(this.ROLE_KEY, response.role);
      this._isAuth.set(true);
      this.lastUserInteractionMs = Date.now();
      this.wasIdlePaused = false;
      this.startHeartbeat();
    }
  }

  private startHeartbeat(): void {
    if (typeof window === 'undefined') return;
    this.attachInteractionListeners();
    if (this.heartbeatTimer !== null) return;

    this.heartbeatTimer = setInterval(() => {
      if (!this.hasValidToken()) {
        this.stopHeartbeat();
        return;
      }
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        return;
      }
      const idleMs = Date.now() - this.lastUserInteractionMs;
      if (idleMs > this.IDLE_CUTOFF_MS) {
        // Pausar heartbeats mientras el usuario está inactivo para no contabilizar horas fantasma
        this.wasIdlePaused = true;
        return;
      }
      this.sendHeartbeat();
    }, this.HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.detachInteractionListeners();
  }

  private attachInteractionListeners(): void {
    if (this.interactionListenersAttached || typeof window === 'undefined') return;
    const events = ['pointerdown', 'keydown', 'click', 'scroll', 'touchstart'];
    events.forEach(evt => window.addEventListener(evt, this.onUserInteraction, { passive: true }));
    this.interactionListenersAttached = true;
  }

  private detachInteractionListeners(): void {
    if (!this.interactionListenersAttached || typeof window === 'undefined') return;
    const events = ['pointerdown', 'keydown', 'click', 'scroll', 'touchstart'];
    events.forEach(evt => window.removeEventListener(evt, this.onUserInteraction));
    this.interactionListenersAttached = false;
  }

  sendHeartbeat(): void {
    const token = this.getToken();
    if (!token) return;
    this.http
      .post(
        `${environment.apiUrl}/api/auth/heartbeat`,
        {},
        { headers: { Authorization: `Bearer ${token}`, 'X-Client-Type': 'web' } }
      )
      .subscribe({ error: () => {} });
  }

  logout(): void {
    const token = this.getToken();
    this.stopHeartbeat();
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.ROLE_KEY);
    this._isAuth.set(false);
    if (token) {
      this.http.post(
        `${environment.apiUrl}/api/auth/logout`,
        {},
        { headers: { Authorization: `Bearer ${token}`, 'X-Client-Type': 'web' } }
      ).subscribe({ error: () => {} });
    }
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  getRole(): string | null {
    return localStorage.getItem(this.ROLE_KEY);
  }

  getEmail(): string | null {
    const token = this.getToken();
    if (!token) return null;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      return payload.sub ?? null;
    } catch {
      return null;
    }
  }

  isAuthenticated(): boolean {
    return this.hasValidToken();
  }

  private hasValidToken(): boolean {
    const token = localStorage.getItem(this.TOKEN_KEY);
    if (!token) return false;
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return false;
      const payload = JSON.parse(atob(parts[1]));
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.ROLE_KEY);
        return false;
      }
      return true;
    } catch {
      return false;
    }
  }
}
