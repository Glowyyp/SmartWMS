// features/supervisor/supervisor.component.ts
// Panel del Supervisor / Jefe de Bodega — SmartWMS

import {
  Component, OnInit, OnDestroy, signal, computed
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTableModule } from '@angular/material/table';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatBadgeModule } from '@angular/material/badge';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatDialogModule } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { AuthService } from '../../core/services/auth.service';
import { OrdersService, Order } from '../../core/services/orders.service';
import { InventoryService, ProductInventory } from '../../core/services/inventory.service';
import { UsersService, UserRecord } from '../../core/services/users.service';
import { WorkOrdersService, WorkOrder, WorkOrderItemIn, Operario } from '../../core/services/work-orders.service';
import { ChatbotComponent } from '../../shared/chatbot/chatbot.component';
import { Subscription, interval } from 'rxjs';
import { switchMap, startWith } from 'rxjs/operators';

interface NewOrderLine {
  sku: string;
  product_name: string;
  available_qty: number;
  quantity: number;
}

@Component({
  selector: 'app-supervisor',
  standalone: true,
  imports: [
    CommonModule, RouterModule, FormsModule,
    MatIconModule, MatButtonModule, MatTabsModule, MatTableModule,
    MatChipsModule, MatTooltipModule, MatProgressBarModule, MatBadgeModule,
    MatSelectModule, MatFormFieldModule, MatInputModule, MatSnackBarModule,
    ChatbotComponent,
  ],
  templateUrl: './supervisor.component.html',
  styleUrls: ['./supervisor.component.scss'],
})
export class SupervisorComponent implements OnInit, OnDestroy {
  userEmail = signal('');
  userRole = signal('');
  activeTab = signal(0);
  selectedStatus = signal<string>('');

  // ── Órdenes (webhook) ──────────────────────────────────────────────────────
  orders = signal<Order[]>([]);
  ordersLoading = signal(false);
  ordersError = signal('');
  orderColumns = ['id', 'external_order_id', 'customer_name', 'total', 'status', 'received_at'];

  // ── Inventario ─────────────────────────────────────────────────────────────
  products = signal<ProductInventory[]>([]);
  productsLoading = signal(false);
  inventorySearch = signal('');
  inventoryColumns = ['sku', 'product_name', 'stock_physical', 'stock_reserved', 'stock_available', 'unit_price', 'reorder_point', 'status', 'actions'];

  showAddForm = signal(false);
  addingProduct = signal(false);
  newProduct = signal({ sku: '', product_name: '', stock_quantity: 0, unit_price: 0, reorder_point: 10, warehouse_location: '' as string | null });

  filteredProducts = computed(() => {
    const q = this.inventorySearch().toLowerCase();
    if (!q) return this.products();
    return this.products().filter(p =>
      p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)
    );
  });

  lowStockCount = computed(() =>
    this.products().filter(p => p.is_low_stock).length
  );

  // ── Usuarios ───────────────────────────────────────────────────────────────
  users = signal<UserRecord[]>([]);
  usersLoading = signal(false);
  userColumns = ['id', 'email', 'full_name', 'role', 'is_active', 'created_at'];

  // ── Pedidos de Bodega (Work Orders) ────────────────────────────────────────
  workOrders = signal<WorkOrder[]>([]);
  workOrdersLoading = signal(false);
  workOrdersError = signal('');
  woStatusFilter = signal<string>('');
  woColumns = ['order_number', 'status', 'assigned_operario_email', 'created_by_email', 'created_at', 'items_count', 'dispatched_by_email', 'dispatched_at', 'actions'];

  pendingWoCount = computed(() =>
    this.workOrders().filter(wo => wo.status === 'pending').length
  );

  // ── Formulario de nuevo pedido ─────────────────────────────────────────────
  showNewOrderForm = signal(false);
  orderLines = signal<NewOrderLine[]>([]);
  skuSearch = signal('');
  creatingOrder = signal(false);
  selectedOperario = signal<string>('');   // email del operario asignado ('' = sin asignar)
  operarios = signal<Operario[]>([]);      // lista para el selector
  operariosLoading = signal(false);

  skuSearchResults = computed(() => {
    const q = this.skuSearch().toLowerCase().trim();
    if (!q) return [];
    return this.products().filter(p =>
      (p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)) &&
      p.available_qty > 0
    ).slice(0, 8);
  });

  // ── IoT simulado ───────────────────────────────────────────────────────────
  iotData = signal({
    temperature: 18.4,
    humidity: 62,
    impactAlert: false,
    lastUpdate: new Date(),
  });

  // ── Métricas BI ────────────────────────────────────────────────────────────
  leadTimeAvg = signal(2.3);
  criticalStockCount = computed(() => this.products().filter(p => p.stock_quantity === 0 || p.is_low_stock).length);

  private pollSub?: Subscription;
  private woPollSub?: Subscription;

  constructor(
    private authService: AuthService,
    private ordersService: OrdersService,
    private inventoryService: InventoryService,
    private usersService: UsersService,
    private workOrdersService: WorkOrdersService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.userEmail.set(this.authService.getEmail() ?? '');
    this.userRole.set(this.authService.getRole() ?? '');

    this.loadOrders();
    this.loadInventory();
    this.loadUsers();
    this.loadWorkOrders();
    this.startIoTSimulation();

    // Poll órdenes webhook cada 30 s
    this.pollSub = interval(30000).pipe(
      startWith(0),
      switchMap(() => this.ordersService.getOrders(this.selectedStatus() || undefined))
    ).subscribe({ next: orders => this.orders.set(orders) });

    // Poll pedidos de bodega cada 15 s (actualización automática para el supervisor)
    this.woPollSub = interval(15000).pipe(
      startWith(0),
      switchMap(() => this.workOrdersService.getWorkOrders(this.woStatusFilter() || undefined))
    ).subscribe({ next: wos => this.workOrders.set(wos) });
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
    this.woPollSub?.unsubscribe();
  }

  // ── Órdenes webhook ────────────────────────────────────────────────────────
  loadOrders(): void {
    this.ordersLoading.set(true);
    this.ordersError.set('');
    this.ordersService.getOrders(this.selectedStatus() || undefined).subscribe({
      next: orders => { this.orders.set(orders); this.ordersLoading.set(false); },
      error: () => { this.ordersError.set('No se pudieron cargar las órdenes.'); this.ordersLoading.set(false); },
    });
  }

  onStatusFilter(): void { this.loadOrders(); }

  // ── Inventario ─────────────────────────────────────────────────────────────
  loadInventory(): void {
    this.productsLoading.set(true);
    this.inventoryService.getProducts().subscribe({
      next: products => { this.products.set(products); this.productsLoading.set(false); },
      error: () => this.productsLoading.set(false),
    });
  }

  updateNewProduct(field: string, value: string | number): void {
    this.newProduct.update(p => ({ ...p, [field]: value }));
  }

  createProduct(): void {
    const p = this.newProduct();
    if (!p.sku.trim() || !p.product_name.trim() || p.unit_price <= 0) {
      this.snackBar.open('Completa SKU, nombre y precio válido.', '', { duration: 3000 });
      return;
    }
    this.addingProduct.set(true);
    this.inventoryService.createProduct(p).subscribe({
      next: created => {
        this.products.update(list => [{ ...created, reserved_qty: 0, available_qty: created.stock_quantity }, ...list]);
        this.showAddForm.set(false);
        this.newProduct.set({ sku: '', product_name: '', stock_quantity: 0, unit_price: 0, reorder_point: 10, warehouse_location: null });
        this.addingProduct.set(false);
        this.snackBar.open(`✅ Producto ${created.sku} creado`, '', { duration: 3000 });
      },
      error: err => {
        this.addingProduct.set(false);
        const msg = err.error?.detail ?? 'Error al crear el producto';
        this.snackBar.open(msg, 'Cerrar', { duration: 5000 });
      },
    });
  }

  deleteProduct(id: number, sku: string): void {
    if (!confirm(`¿Eliminar el producto ${sku}? Esta acción no se puede deshacer.`)) return;
    this.inventoryService.deleteProduct(id).subscribe({
      next: () => { this.products.update(list => list.filter(p => p.id !== id)); this.snackBar.open(`Producto ${sku} eliminado`, '', { duration: 3000 }); },
      error: () => this.snackBar.open('Error al eliminar. Solo el admin puede eliminar.', 'Cerrar', { duration: 4000 }),
    });
  }

  // ── Usuarios ───────────────────────────────────────────────────────────────
  loadUsers(): void {
    this.usersLoading.set(true);
    this.usersService.getUsers().subscribe({
      next: users => { this.users.set(users); this.usersLoading.set(false); },
      error: () => this.usersLoading.set(false),
    });
  }

  // ── Work Orders ────────────────────────────────────────────────────────────
  loadWorkOrders(): void {
    this.workOrdersLoading.set(true);
    this.workOrdersError.set('');
    this.workOrdersService.getWorkOrders(this.woStatusFilter() || undefined).subscribe({
      next: wos => { this.workOrders.set(wos); this.workOrdersLoading.set(false); },
      error: () => { this.workOrdersError.set('No se pudieron cargar los pedidos.'); this.workOrdersLoading.set(false); },
    });
  }

  onWoStatusFilter(): void { this.loadWorkOrders(); }

  // ── Formulario de Nuevo Pedido ─────────────────────────────────────────────
  openNewOrderForm(): void {
    this.orderLines.set([]);
    this.skuSearch.set('');
    this.selectedOperario.set('');
    this.showNewOrderForm.set(true);
    // Actualizar inventario para tener stock disponible fresco
    this.loadInventory();
    // Cargar lista de operarios para el selector
    this.loadOperarios();
  }

  loadOperarios(): void {
    this.operariosLoading.set(true);
    this.workOrdersService.getOperarios().subscribe({
      next: ops => { this.operarios.set(ops); this.operariosLoading.set(false); },
      error: () => this.operariosLoading.set(false),
    });
  }

  addLineFromProduct(product: ProductInventory): void {
    const existing = this.orderLines().find(l => l.sku === product.sku);
    if (existing) {
      this.snackBar.open(`${product.sku} ya está en el pedido. Ajusta la cantidad.`, '', { duration: 2500 });
      return;
    }
    this.orderLines.update(lines => [...lines, {
      sku: product.sku,
      product_name: product.product_name,
      available_qty: product.available_qty,
      quantity: 1,
    }]);
    this.skuSearch.set('');
  }

  updateLineQty(sku: string, qty: number): void {
    this.orderLines.update(lines =>
      lines.map(l => l.sku === sku ? { ...l, quantity: Math.max(1, Math.min(qty, l.available_qty)) } : l)
    );
  }

  removeLine(sku: string): void {
    this.orderLines.update(lines => lines.filter(l => l.sku !== sku));
  }

  confirmNewOrder(): void {
    const lines = this.orderLines();
    if (lines.length === 0) {
      this.snackBar.open('Agrega al menos un producto al pedido.', '', { duration: 2500 });
      return;
    }
    const invalid = lines.find(l => l.quantity < 1);
    if (invalid) {
      this.snackBar.open(`Cantidad inválida para ${invalid.sku}.`, '', { duration: 2500 });
      return;
    }

    this.creatingOrder.set(true);
    const payload = {
      items: lines.map(l => ({ sku: l.sku, quantity: l.quantity } as WorkOrderItemIn)),
      assigned_operario_email: this.selectedOperario() || null,
    };
    this.workOrdersService.createWorkOrder(payload).subscribe({
      next: wo => {
        this.workOrders.update(wos => [wo, ...wos]);
        this.showNewOrderForm.set(false);
        this.creatingOrder.set(false);
        this.snackBar.open(`✅ Pedido ${wo.order_number} creado`, 'OK', { duration: 4000 });
        // Recargar inventario para reflejar las nuevas reservas
        this.loadInventory();
      },
      error: err => {
        this.creatingOrder.set(false);
        const msg = err.error?.detail ?? 'Error al crear el pedido';
        this.snackBar.open(msg, 'Cerrar', { duration: 6000 });
      },
    });
  }

  cancelWorkOrder(wo: WorkOrder): void {
    if (!confirm(`¿Cancelar el pedido ${wo.order_number}? La reserva de stock será liberada.`)) return;
    this.workOrdersService.cancel(wo.id).subscribe({
      next: updated => {
        this.workOrders.update(wos => wos.map(w => w.id === updated.id ? updated : w));
        this.snackBar.open(`Pedido ${updated.order_number} cancelado`, '', { duration: 3000 });
        this.loadInventory(); // Actualizar stock disponible
      },
      error: err => this.snackBar.open(err.error?.detail ?? 'Error al cancelar', 'Cerrar', { duration: 4000 }),
    });
  }

  // ── Helpers de UI ──────────────────────────────────────────────────────────
  getOrderStatusClass(status: string): string {
    const map: Record<string, string> = {
      completed: 'chip-success', processing: 'chip-warning',
      received: 'chip-info', failed: 'chip-danger', cancelled: 'chip-muted',
    };
    return map[status] ?? 'chip-muted';
  }

  getWoStatusClass(status: string): string {
    const map: Record<string, string> = {
      pending: 'chip-warning', dispatched: 'chip-success', cancelled: 'chip-muted',
    };
    return map[status] ?? 'chip-muted';
  }

  getWoStatusLabel(status: string): string {
    const map: Record<string, string> = {
      pending: 'Pendiente', dispatched: 'Despachado', cancelled: 'Cancelado',
    };
    return map[status] ?? status;
  }

  getStockStatus(p: ProductInventory): 'critical' | 'warning' | 'ok' {
    if (p.stock_quantity === 0) return 'critical';
    if (p.is_low_stock) return 'critical';
    const ratio = p.stock_quantity / p.reorder_point;
    return ratio <= 2 ? 'warning' : 'ok';
  }

  getRoleLabel(role: string): string {
    const map: Record<string, string> = {
      admin: 'Administrador', supervisor: 'Supervisor', operario: 'Operario',
    };
    return map[role] ?? role;
  }

  getRoleBadgeClass(role: string): string {
    const map: Record<string, string> = {
      admin: 'role-admin', supervisor: 'role-supervisor', operario: 'role-operario',
    };
    return map[role] ?? '';
  }

  private startIoTSimulation(): void {
    setInterval(() => {
      this.iotData.update(d => ({
        temperature: +(d.temperature + (Math.random() - 0.5) * 0.3).toFixed(1),
        humidity: Math.min(100, Math.max(30, d.humidity + Math.round((Math.random() - 0.5) * 2))),
        impactAlert: Math.random() < 0.05,
        lastUpdate: new Date(),
      }));
    }, 5000);
  }

  logout(): void { this.authService.logout(); }
}
