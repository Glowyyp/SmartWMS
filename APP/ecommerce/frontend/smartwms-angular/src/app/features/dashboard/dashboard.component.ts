// features/dashboard/dashboard.component.ts
// Dashboard principal con métricas de órdenes e inventario

import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';

// Angular Material
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatChipsModule } from '@angular/material/chips';
import { MatMenuModule } from '@angular/material/menu';

import { AuthService } from '../../core/services/auth.service';

interface MetricCard {
  id: string;
  title: string;
  value: string | number;
  subtitle: string;
  icon: string;
  trend: 'up' | 'down' | 'neutral';
  trendValue: string;
  color: 'primary' | 'success' | 'warning' | 'danger';
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatToolbarModule,
    MatChipsModule,
    MatMenuModule,
  ],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss'],
})
export class DashboardComponent implements OnInit {
  userRole = signal<string>('');

  metrics: MetricCard[] = [
    { id: 'metric-orders', title: 'Órdenes Hoy',      value: 142,      subtitle: 'webhooks procesados', icon: 'shopping_cart',   trend: 'up',      trendValue: '+12%', color: 'primary' },
    { id: 'metric-stock',  title: 'SKUs en Stock',     value: 1842,     subtitle: 'productos activos',   icon: 'inventory_2',     trend: 'neutral', trendValue: '0%',   color: 'success' },
    { id: 'metric-low',    title: 'Stock Crítico',     value: 3,        subtitle: 'bajo punto de reorden', icon: 'warning',       trend: 'down',    trendValue: '-1',   color: 'warning' },
    { id: 'metric-rev',    title: 'Ingresos del Día',  value: '$4,821', subtitle: 'suma de órdenes',     icon: 'payments',        trend: 'up',      trendValue: '+8%',  color: 'primary' },
  ];

  recentOrders = [
    { id: 'ORD-001', customer: 'María González', total: '$74.97',  status: 'completed', time: 'hace 5 min' },
    { id: 'ORD-002', customer: 'Carlos Rodríguez', total: '$189.99', status: 'completed', time: 'hace 12 min' },
    { id: 'ORD-003', customer: 'Ana Martínez',    total: '$29.99',  status: 'failed',    time: 'hace 18 min' },
    { id: 'ORD-004', customer: 'Pedro Sánchez',   total: '$459.98', status: 'completed', time: 'hace 25 min' },
    { id: 'ORD-005', customer: 'Laura Torres',    total: '$14.99',  status: 'processing', time: 'hace 30 min' },
  ];

  constructor(private authService: AuthService, private router: Router) {}

  ngOnInit(): void {
    const role = this.authService.getRole();
    this.userRole.set(role ?? 'operario');

    // Redirigir al panel correspondiente según rol
    if (role === 'admin' || role === 'supervisor') {
      this.router.navigate(['/supervisor']);
    } else {
      this.router.navigate(['/operario']);
    }
  }

  logout(): void {
    this.authService.logout();
  }

  getStatusIcon(status: string): string {
    const icons: Record<string, string> = {
      completed: 'check_circle',
      failed: 'cancel',
      processing: 'hourglass_empty',
    };
    return icons[status] ?? 'help';
  }
}
