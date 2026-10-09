// core/interceptors/auth.interceptor.ts
// Interceptor HTTP que inyecta automáticamente el JWT en cada request saliente

import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from '../services/auth.service';

/**
 * Interceptor funcional (Angular 17+).
 * Clona cada request saliente y añade el header Authorization: Bearer <token>.
 * Si no hay token, el request pasa sin modificación.
 *
 * Registro en app.config.ts:
 *   provideHttpClient(withInterceptors([authInterceptor]))
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const authService = inject(AuthService);
  const token = authService.getToken();

  if (token) {
    const cloned = req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`,
      },
    });
    return next(cloned);
  }

  return next(req);
};
