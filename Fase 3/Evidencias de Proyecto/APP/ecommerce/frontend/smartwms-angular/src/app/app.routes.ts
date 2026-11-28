// app.routes.ts — Configuración de rutas con lazy loading y guards de rol
// Roles: 'admin' | 'supervisor' | 'operario'

import { Routes } from '@angular/router';
import { authGuard } from './core/guards/auth.guard';
import { roleGuard } from './core/guards/role.guard';

export const routes: Routes = [
  // ─── Ruta raíz: redirige al panel correcto según rol ──────────────────────
  {
    path: '',
    canActivate: [authGuard],
    // El dashboard redirige internamente según el rol almacenado
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
  },

  // ─── Autenticación (pública) ──────────────────────────────────────────────
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login/login.component').then(m => m.LoginComponent),
    title: 'Iniciar Sesión — SmartWMS',
  },

  // ─── Panel Supervisor (admin y supervisor) ────────────────────────────────
  {
    path: 'supervisor',
    canActivate: [authGuard, roleGuard(['admin', 'supervisor'])],
    loadComponent: () =>
      import('./features/supervisor/supervisor.component').then(m => m.SupervisorComponent),
    title: 'Supervisor — SmartWMS',
  },

  // ─── Panel Operario ───────────────────────────────────────────────────────
  {
    path: 'operario',
    canActivate: [authGuard, roleGuard(['operario', 'admin'])],
    loadComponent: () =>
      import('./features/operario/operario.component').then(m => m.OperarioComponent),
    title: 'Operario — SmartWMS',
  },

  // ─── Inventario (protegida, cualquier rol) ────────────────────────────────
  {
    path: 'inventory',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/inventory/inventory.component').then(m => m.InventoryComponent),
    title: 'Inventario — SmartWMS',
  },

  // ─── Dashboard genérico (legado, redirige según rol) ─────────────────────
  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
    title: 'Dashboard — SmartWMS',
  },

  // ─── Wildcard ─────────────────────────────────────────────────────────────
  {
    path: '**',
    redirectTo: '/dashboard',
  },
];
