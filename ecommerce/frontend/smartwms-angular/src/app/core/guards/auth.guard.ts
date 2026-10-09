// core/guards/auth.guard.ts
// Guard funcional (estilo Angular 17+) que protege rutas privadas
// Verifica la presencia de un JWT en localStorage antes de permitir navegación

import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/**
 * Guard funcional para proteger rutas que requieren autenticación.
 *
 * Si el usuario no tiene un token válido, redirige a /login
 * y devuelve false para cancelar la navegación actual.
 *
 * Uso en routes:
 *   canActivate: [authGuard]
 */
export const authGuard: CanActivateFn = (_route, _state) => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.isAuthenticated()) {
    return true;
  }

  // No autenticado: redirigir a login
  router.navigate(['/login']);
  return false;
};
