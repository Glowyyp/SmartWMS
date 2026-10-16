// core/services/auth.service.ts
// Servicio de autenticación: gestiona el token JWT en localStorage
// y expone helpers de login/logout/estado

import { Injectable, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { tap } from 'rxjs/operators';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface LoginPayload {
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  role: string;  // Retornado por TokenResponse del backend
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'smartwms_token';
  private readonly ROLE_KEY  = 'smartwms_role';

  // Signal reactivo para el estado de autenticación
  private _isAuth = signal<boolean>(this.hasValidToken());
  readonly isAuth = computed(() => this._isAuth());

  constructor(private http: HttpClient, private router: Router) {}

  /**
   * Envía credenciales al backend y almacena el token JWT.
   * El operador tap() actúa como side-effect sin alterar el stream.
   */
  login(credentials: LoginPayload): Observable<AuthResponse> {
    // OAuth2PasswordRequestForm espera form-data con 'username' y 'password'
    const formData = new FormData();
    formData.append('username', credentials.email);
    formData.append('password', credentials.password);

    return this.http
      .post<AuthResponse>(`${environment.apiUrl}/api/auth/login`, formData)
      .pipe(
        tap((response) => {
          localStorage.setItem(this.TOKEN_KEY, response.access_token);
          localStorage.setItem(this.ROLE_KEY, response.role);
          this._isAuth.set(true);
        })
      );
  }

  logout(): void {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.ROLE_KEY);
    this._isAuth.set(false);
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  getRole(): string | null {
    return localStorage.getItem(this.ROLE_KEY);
  }

  /**
   * Extrae el email del JWT almacenado (campo 'sub' del payload).
   * Decodifica en cliente sin validar firma — solo para mostrar en UI.
   */
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

  /** Verifica que exista un token y que su firma no haya expirado según exp */
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
