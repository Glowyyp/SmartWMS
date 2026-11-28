// core/guards/role.guard.ts
// Guard funcional que verifica el rol del usuario almacenado en localStorage
// Roles unificados del sistema: 'admin' | 'supervisor' | 'operario'

import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/**
 * Fábrica de guards por rol.
 *
 * Roles válidos: 'admin' | 'supervisor' | 'operario'
 *
 * Uso en routes:
 *   canActivate: [roleGuard(['supervisor', 'admin'])]
 *   canActivate: [roleGuard(['operario', 'admin'])]
 *
 * Lógica de redirección cuando el rol no coincide:
 *   - admin / supervisor  → /supervisor
 *   - operario            → /operario
 */
export function roleGuard(allowedRoles: string[]): CanActivateFn {
  return (_route, _state) => {
    const authService = inject(AuthService);
    const router = inject(Router);

    if (!authService.isAuthenticated()) {
      router.navigate(['/login']);
      return false;
    }

    const role = authService.getRole();
    if (role && allowedRoles.includes(role)) {
      return true;
    }

    // Rol no autorizado: redirigir al panel correspondiente
    if (role === 'admin' || role === 'supervisor') {
      router.navigate(['/supervisor']);
    } else {
      // operario (o rol desconocido)
      router.navigate(['/operario']);
    }
    return false;
  };
}
