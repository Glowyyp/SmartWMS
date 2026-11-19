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
import { OrdersService, Order, InsufficientStockItem } from '../../core/services/orders.service';
import { InventoryService, ProductInventory, PendingReception } from '../../core/services/inventory.service';
import { UsersService, UserRecord } from '../../core/services/users.service';
import { WorkOrdersService, WorkOrder, WorkOrderItemIn, WorkOrderUpdate, Operario } from '../../core/services/work-orders.service';
import { generateCode128SvgDataUri } from '../../core/utils/barcode.util';
import { ChatbotComponent } from '../../shared/chatbot/chatbot.component';
import { Subscription, interval, forkJoin } from 'rxjs';
import { switchMap, startWith } from 'rxjs/operators';

type OrderStatusOption = 'received' | 'processing' | 'completed' | 'rejected';

interface NewOrderLine {
  sku: string;
  product_name: string;
  available_qty: number;
  quantity: number;
}

interface EditOrderLine {
  sku: string;
  product_name: string;
  available_qty: number;
  quantity: number;
  unit_price: number;
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
  paidOrders = computed(() => this.orders().filter(o => this.isOrderPaid(o)));
  ordersLoading = signal(false);
  ordersError = signal('');
  expandedOrderId = signal<number | null>(null);

  // ── Inventario ─────────────────────────────────────────────────────────────
  products = signal<ProductInventory[]>([]);
  productsLoading = signal(false);
  inventorySearch = signal('');
  expandedProductQrId = signal<number | null>(null);

  showAddForm = signal(false);
  addingProduct = signal(false);
  newProduct = signal<{
    sku: string;
    product_name: string;
    stock_quantity: number;
    unit_price: number;
    reorder_point: number;
    warehouse_location: string | null;
    length?: number | null;
    width?: number | null;
    height?: number | null;
    weight?: number | null;
  }>({
    sku: '',
    product_name: '',
    stock_quantity: 0,
    unit_price: 0,
    reorder_point: 10,
    warehouse_location: null,
    length: null,
    width: null,
    height: null,
    weight: null
  });

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
    this.workOrders().filter(wo => wo.status === 'pending' || wo.status === 'por_asignar').length
  );

  // ── Órdenes webhook ────────────────────────────────────────────────────────
  pendingOrderStatuses = signal<Record<number, OrderStatusOption>>({});
  savingOrderStatuses = signal(false);
  pendingOrderStatusCount = computed(() => Object.keys(this.pendingOrderStatuses()).length);

  // ── Recepciones Pendientes ────────────────────────────────────────────────
  receptions = signal<PendingReception[]>([]);
  receptionsLoading = signal(false);
  receptionColumns = ['id', 'sku', 'expected_quantity', 'received_quantity', 'status', 'notes', 'created_at', 'actions'];
  showNewReceptionForm = signal(false);
  newReception = signal({ sku: '', expected_quantity: 0, notes: '' });
  confirmingReception = signal<PendingReception | null>(null);
  confirmQty = signal<number>(0);
  confirmCloseShortage = signal<boolean>(false);
  confirmNotes = signal<string>('');
  editingReception = signal<PendingReception | null>(null);
  editReceptionExpected = signal<number>(1);
  editReceptionReceived = signal<number>(0);
  editReceptionNotes = signal<string>('');
  savingReceptionAction = signal<boolean>(false);

  // ── Formulario de nuevo pedido ─────────────────────────────────────────────
  showNewOrderForm = signal(false);
  orderLines = signal<NewOrderLine[]>([]);
  skuSearch = signal('');
  orderLookupRef = signal('');
  loadingOrderLookup = signal(false);
  orderLookupError = signal('');
  orderLookupInsufficient = signal<InsufficientStockItem[]>([]);
  loadedOrderIds = signal<number[]>([]);
  creatingOrder = signal(false);
  selectedOperario = signal<string>('');   // email del operario asignado ('' = sin asignar)
  operarios = signal<Operario[]>([]);      // lista para el selector
  operariosLoading = signal(false);

  skuSearchResults = computed(() => {
    const q = this.skuSearch().toLowerCase().trim();
    if (!q) return [];
    return this.products().filter(p =>
      (p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)) &&
      (p.available_qty > 0)
    ).slice(0, 8);
  });

  // ── Formulario de edición de pedido ────────────────────────────────────────
  editingOrder = signal<WorkOrder | null>(null);
  savingEditOrder = signal(false);
  editOrderError = signal('');
  editSelectedOperario = signal<string>('');
  editSelectedStatus = signal<string>('');
  editOrderLines = signal<EditOrderLine[]>([]);
  editSkuSearch = signal('');

  editSkuSearchResults = computed(() => {
    const q = this.editSkuSearch().toLowerCase().trim();
    if (!q) return [];
    return this.products().filter(p =>
      (p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)) &&
      (p.available_qty > 0 || this.isSkuInEditingOrder(p.sku))
    ).slice(0, 8);
  });

  // ── Formulario de Nueva Recepción ──────────────────────────────────────────
  receptionSkuSearch = signal('');
  receptionSkuSearchResults = computed(() => {
    const q = this.receptionSkuSearch().toLowerCase().trim();
    if (!q) return [];
    return this.products().filter(p =>
      p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)
    ).slice(0, 8);
  });

  selectReceptionSku(product: ProductInventory): void {
    this.newReception.update(r => ({ ...r, sku: product.sku }));
    this.receptionSkuSearch.set('');
  }

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
  private usersPollSub?: Subscription;

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
    this.loadReceptions();
    this.loadOperarios();
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

    // Poll usuarios conectados cada 10 s para reflejar conexiones/desconexiones sin recargar
    this.usersPollSub = interval(10000).pipe(
      switchMap(() => this.usersService.getUsers())
    ).subscribe({ next: users => this.users.set(users) });
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
    this.woPollSub?.unsubscribe();
    this.usersPollSub?.unsubscribe();
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

  toggleOrderExpand(order: Order): void {
    this.expandedOrderId.update(cur => cur === order.id ? null : order.id);
  }

  normalizeOrderStatusForSelect(status: string): OrderStatusOption {
    const s = (status || '').toLowerCase();
    if (s === 'processing') return 'processing';
    if (s === 'completed') return 'completed';
    if (s === 'rejected') return 'rejected';
    return 'received';
  }

  getDraftOrderStatus(order: Order): OrderStatusOption {
    return this.pendingOrderStatuses()[order.id] ?? this.normalizeOrderStatusForSelect(order.status);
  }

  hasPendingOrderStatus(order: Order): boolean {
    const draft = this.pendingOrderStatuses()[order.id];
    return !!draft && draft !== this.normalizeOrderStatusForSelect(order.status);
  }

  onOrderStatusChange(order: Order, event: Event): void {
    const selectEl = event.target as HTMLSelectElement;
    const newStatus = selectEl.value as OrderStatusOption;
    const current = this.normalizeOrderStatusForSelect(order.status);

    this.pendingOrderStatuses.update(map => {
      const next = { ...map };
      if (!newStatus || newStatus === current) {
        delete next[order.id];
      } else {
        next[order.id] = newStatus;
      }
      return next;
    });
  }

  discardOrderStatusChange(order: Order): void {
    this.pendingOrderStatuses.update(map => {
      const next = { ...map };
      delete next[order.id];
      return next;
    });
  }

  confirmSingleOrderStatus(order: Order): void {
    const newStatus = this.pendingOrderStatuses()[order.id];
    if (!newStatus || newStatus === this.normalizeOrderStatusForSelect(order.status)) return;

    this.savingOrderStatuses.set(true);
    this.ordersService.updateOrderStatus(order.id, newStatus).subscribe({
      next: updated => {
        this.orders.update(list => list.map(o => o.id === updated.id ? updated : o));
        this.discardOrderStatusChange(order);
        this.savingOrderStatuses.set(false);
        this.snackBar.open(
          `✅ Orden #${updated.id} (${updated.external_order_id}) confirmada como "${this.getOrderStatusLabel(updated.status)}"`,
          'OK',
          { duration: 3500 }
        );
      },
      error: err => {
        this.savingOrderStatuses.set(false);
        const msg = err.error?.detail ?? 'No se pudo actualizar el estado de la orden.';
        this.snackBar.open(`❌ ${msg}`, 'Cerrar', { duration: 4500 });
      },
    });
  }

  confirmAllOrderStatuses(): void {
    const drafts = this.pendingOrderStatuses();
    const entries = Object.entries(drafts);
    if (entries.length === 0) {
      this.snackBar.open('No hay cambios de estado pendientes por confirmar.', 'OK', { duration: 2500 });
      return;
    }

    const calls = entries
      .map(([idStr, status]) => ({ id: Number(idStr), status }))
      .filter(({ id, status }) => {
        const order = this.orders().find(o => o.id === id);
        return order && status !== this.normalizeOrderStatusForSelect(order.status);
      });

    if (calls.length === 0) {
      this.pendingOrderStatuses.set({});
      return;
    }

    this.savingOrderStatuses.set(true);
    forkJoin(calls.map(c => this.ordersService.updateOrderStatus(c.id, c.status))).subscribe({
      next: updatedList => {
        const updatedMap = new Map(updatedList.map(u => [u.id, u]));
        this.orders.update(list => list.map(o => updatedMap.get(o.id) ?? o));
        this.pendingOrderStatuses.set({});
        this.savingOrderStatuses.set(false);
        this.snackBar.open(
          `✅ ${updatedList.length} estado(s) de orden confirmados correctamente`,
          'OK',
          { duration: 3500 }
        );
      },
      error: err => {
        this.savingOrderStatuses.set(false);
        const msg = err.error?.detail ?? 'Error al confirmar los estados de las órdenes.';
        this.snackBar.open(`❌ ${msg}`, 'Cerrar', { duration: 4500 });
      },
    });
  }

  productCodeModeMap = signal<Record<number, 'qr' | 'barcode'>>({});
  private barcodeCache = new Map<string, string>();

  toggleProductQr(product: ProductInventory): void {
    this.expandedProductQrId.update(cur => cur === product.id ? null : product.id);
  }

  getProductCodeMode(productId: number): 'qr' | 'barcode' {
    return this.productCodeModeMap()[productId] ?? 'qr';
  }

  toggleProductCodeMode(productId: number): void {
    const nextMode = this.getProductCodeMode(productId) === 'qr' ? 'barcode' : 'qr';
    this.productCodeModeMap.update(prev => ({ ...prev, [productId]: nextMode }));
  }

  getBarcodeDataUri(sku: string): string {
    const clean = (sku || '').trim();
    const cached = this.barcodeCache.get(clean);
    if (cached) return cached;
    const uri = generateCode128SvgDataUri(clean);
    this.barcodeCache.set(clean, uri);
    return uri;
  }

  // ── Inventario ─────────────────────────────────────────────────────────────
  editingProduct = signal<ProductInventory | null>(null);

  loadInventory(): void {
    this.productsLoading.set(true);
    this.inventoryService.getProducts().subscribe({
      next: products => { this.products.set(products); this.productsLoading.set(false); },
      error: () => this.productsLoading.set(false),
    });
  }

  updateNewProduct(field: string, value: string | number): void {
    if (this.editingProduct()) {
      this.editingProduct.update(p => p ? { ...p, [field]: value } : null);
    } else {
      this.newProduct.update(p => ({ ...p, [field]: value }));
    }
  }

  editProduct(p: ProductInventory): void {
    this.editingProduct.set({ ...p });
    this.showAddForm.set(true);
  }

  cancelEdit(): void {
    this.editingProduct.set(null);
    this.showAddForm.set(false);
  }

  createProduct(): void {
    const isEdit = !!this.editingProduct();
    const p = isEdit ? this.editingProduct()! : this.newProduct();
    if (!p.sku.trim() || !p.product_name.trim() || p.unit_price <= 0) {
      this.snackBar.open('Completa SKU, nombre y precio válido.', '', { duration: 3000 });
      return;
    }
    this.addingProduct.set(true);
    
    if (isEdit) {
      const editProd = this.editingProduct()!;
      this.inventoryService.updateProduct(editProd.id, editProd).subscribe({
        next: updated => {
          this.products.update(list => list.map(item => item.id === updated.id ? { ...updated, reserved_qty: item.reserved_qty, available_qty: updated.stock_quantity - item.reserved_qty } : item));
          this.cancelEdit();
          this.addingProduct.set(false);
          this.snackBar.open(`✅ Producto ${updated.sku} actualizado`, '', { duration: 3000 });
        },
        error: err => {
          this.addingProduct.set(false);
          const msg = err.error?.detail ?? 'Error al actualizar el producto';
          this.snackBar.open(msg, 'Cerrar', { duration: 5000 });
        }
      });
    } else {
      this.inventoryService.createProduct(p).subscribe({
        next: created => {
          this.products.update(list => [{ ...created, reserved_qty: 0, available_qty: created.stock_quantity }, ...list]);
          this.showAddForm.set(false);
          this.newProduct.set({ sku: '', product_name: '', stock_quantity: 0, unit_price: 0, reorder_point: 10, warehouse_location: null, length: null, width: null, height: null, weight: null });
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
  }

  deleteProduct(id: number, sku: string): void {
    if (!confirm(`¿Eliminar el producto ${sku}? Esta acción no se puede deshacer.`)) return;
    this.inventoryService.deleteProduct(id).subscribe({
      next: () => { this.products.update(list => list.filter(p => p.id !== id)); this.snackBar.open(`Producto ${sku} eliminado`, '', { duration: 3000 }); },
      error: () => this.snackBar.open('Error al eliminar. Solo el admin puede eliminar.', 'Cerrar', { duration: 4000 }),
    });
  }

  // ── Usuarios ───────────────────────────────────────────────────────────────
  visibleUsers = computed(() => {
    const role = this.userRole();
    const list = this.users();
    if (role === 'admin') return list;
    return list.filter(u => u.role !== 'admin');
  });

  loadUsers(): void {
    this.usersLoading.set(true);
    this.usersService.getUsers().subscribe({
      next: users => { this.users.set(users); this.usersLoading.set(false); },
      error: () => this.usersLoading.set(false),
    });
  }

  getUserDisplayName(u: UserRecord): string {
    return (u.full_name || '').trim() || u.username || u.email || 'Usuario';
  }

  getUserLastConnection(u: UserRecord): string | null {
    return u.last_seen_at || u.last_login_at || null;
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
    this.orderLookupRef.set('');
    this.orderLookupError.set('');
    this.orderLookupInsufficient.set([]);
    this.loadedOrderIds.set([]);
    this.selectedOperario.set('');
    this.showNewOrderForm.set(true);
    // Actualizar inventario para tener stock disponible fresco
    this.loadInventory();
    // Cargar lista de operarios para el selector
    this.loadOperarios();
  }

  loadItemsFromOrder(): void {
    const ref = this.orderLookupRef().trim();
    if (!ref || this.loadingOrderLookup()) {
      if (!ref) {
        this.orderLookupError.set('Ingresa el número o ID de la orden que deseas cargar.');
        this.orderLookupInsufficient.set([]);
      }
      return;
    }

    this.loadingOrderLookup.set(true);
    this.orderLookupError.set('');
    this.orderLookupInsufficient.set([]);

    const existingQuantities: Record<string, number> = {};
    for (const line of this.orderLines()) {
      existingQuantities[line.sku] = line.quantity;
    }

    this.ordersService.prepareWorkOrder(ref, existingQuantities).subscribe({
      next: res => {
        this.loadingOrderLookup.set(false);
        if (this.loadedOrderIds().includes(res.order_id)) {
          this.orderLookupError.set(`La orden #${res.order_id} (${res.external_order_id}) ya fue cargada en este pedido.`);
          return;
        }
        if (!res.ok) {
          this.orderLookupInsufficient.set(res.insufficient_items || []);
          this.orderLookupError.set(res.error_message || 'No se pudo completar pedido por falta de stock.');
          return;
        }

        // Combinar con líneas existentes sin duplicar SKUs
        this.orderLines.update(currentLines => {
          const updated = [...currentLines];
          for (const item of res.items) {
            const idx = updated.findIndex(l => l.sku === item.sku);
            if (idx >= 0) {
              updated[idx] = {
                ...updated[idx],
                available_qty: item.available_qty,
                quantity: updated[idx].quantity + item.quantity,
              };
            } else {
              updated.push({
                sku: item.sku,
                product_name: item.product_name,
                available_qty: item.available_qty,
                quantity: item.quantity,
              });
            }
          }
          return updated;
        });

        this.loadedOrderIds.update(ids => [...ids, res.order_id]);
        this.orderLookupRef.set('');
        this.snackBar.open(
          `✅ Productos de la orden #${res.order_id} (${res.external_order_id}) cargados correctamente`,
          'OK',
          { duration: 3500 }
        );
      },
      error: err => {
        this.loadingOrderLookup.set(false);
        this.orderLookupInsufficient.set([]);
        this.orderLookupError.set(err.error?.detail ?? `No se pudo consultar la orden "${ref}".`);
      },
    });
  }

  loadOperarios(): void {
    this.operariosLoading.set(true);
    this.workOrdersService.getOperarios().subscribe({
      next: ops => { this.operarios.set(ops); this.operariosLoading.set(false); },
      error: () => this.operariosLoading.set(false),
    });
  }

  addLineFromProduct(product: ProductInventory): void {
    if (product.available_qty <= 0) {
      this.snackBar.open(`${product.sku} no tiene stock disponible para agregar al pedido.`, 'Cerrar', { duration: 3000 });
      return;
    }
    const existing = this.orderLines().find(l => l.sku === product.sku);
    if (existing) {
      this.snackBar.open(`${product.sku} ya está en el pedido. Ajusta la cantidad.`, '', { duration: 2500 });
      return;
    }
    const maxQty = product.available_qty;
    this.orderLines.update(lines => [...lines, {
      sku: product.sku,
      product_name: product.product_name,
      available_qty: maxQty,
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
    const op = this.operarios().find(o => o.email === this.selectedOperario());
    const payload = {
      items: lines.map(l => ({ sku: l.sku, quantity: l.quantity } as WorkOrderItemIn)),
      assigned_operario_id: op ? op.id : null,
      assigned_operario_email: op ? op.email : null,
    };
    this.workOrdersService.createWorkOrder(payload).subscribe({
      next: wo => {
        this.workOrders.update(wos => [wo, ...wos]);
        this.showNewOrderForm.set(false);
        this.creatingOrder.set(false);
        this.orderLines.set([]);
        this.orderLookupRef.set('');
        this.orderLookupError.set('');
        this.orderLookupInsufficient.set([]);
        this.loadedOrderIds.set([]);
        this.selectedOperario.set('');
        this.snackBar.open(`✅ Pedido ${wo.order_number} creado (${this.getWoStatusLabel(wo.status)})`, 'OK', { duration: 4000 });
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
    if (wo.status === 'dispatched') {
      this.snackBar.open('❌ No se puede cancelar un pedido que ya ha sido despachado.', 'Cerrar', { duration: 4000 });
      return;
    }
    if (wo.status === 'cancelled') {
      this.snackBar.open('⚠️ Este pedido ya se encuentra cancelado.', 'Cerrar', { duration: 3000 });
      return;
    }
    const confirmed = confirm(
      `¿Estás seguro de que deseas cancelar el pedido ${wo.order_number}?\n\n` +
      `• La reserva de stock físico asociada será liberada inmediatamente.\n` +
      `• Esta acción quedará registrada en el historial de auditoría.\n` +
      `• No se podrá reactivar posteriormente.`
    );
    if (!confirmed) return;

    this.workOrdersService.cancel(wo.id).subscribe({
      next: updated => {
        this.workOrders.update(wos => wos.map(w => w.id === updated.id ? updated : w));
        this.snackBar.open(`✅ Pedido ${updated.order_number} cancelado correctamente. Reserva liberada.`, 'OK', { duration: 4000 });
        this.loadInventory(); // Actualizar stock disponible
      },
      error: err => {
        const msg = err.error?.detail ?? 'Error al cancelar pedido';
        this.snackBar.open(`❌ ${msg}`, 'Cerrar', { duration: 5000 });
      },
    });
  }

  onStatusChange(wo: WorkOrder, event: any): void {
    const targetStatus = event.target.value;
    if (!targetStatus || targetStatus === wo.status) return;

    if (targetStatus === 'cancelled') {
      this.cancelWorkOrder(wo);
      return;
    }

    this.workOrdersService.updateWorkOrder(wo.id, { status: targetStatus }).subscribe({
      next: updated => {
        this.workOrders.update(wos => wos.map(w => w.id === updated.id ? updated : w));
        this.snackBar.open(
          `✅ Pedido ${wo.order_number} actualizado a estado "${this.getWoStatusLabel(updated.status)}"`,
          'OK',
          { duration: 3500 }
        );
        this.loadInventory();
      },
      error: err => {
        const msg = err.error?.detail ?? 'No se pudo actualizar el estado';
        this.snackBar.open(`❌ ${msg}`, 'Cerrar', { duration: 4500 });
        this.loadWorkOrders(); // Revertir selector
      }
    });
  }

  assignWo(wo: WorkOrder, event: any): void {
    const email = event.target.value;
    const op = this.operarios().find(o => o.email === email);
    const op_id = op ? op.id : null;
    const op_email = op ? op.email : null;
    
    this.workOrdersService.assignWorkOrder(wo.id, op_id, op_email).subscribe({
      next: updated => {
        this.workOrders.update(wos => wos.map(w => w.id === updated.id ? updated : w));
        const statusLabel = this.getWoStatusLabel(updated.status);
        const opMsg = updated.assigned_operario_email ? `asignado a ${updated.assigned_operario_email}` : 'sin asignar';
        this.snackBar.open(`✅ Pedido ${wo.order_number} ${opMsg} (${statusLabel})`, 'OK', { duration: 3000 });
      },
      error: err => {
        const msg = err.error?.detail ?? 'Error al asignar operario';
        this.snackBar.open(`❌ ${msg}`, 'Cerrar', { duration: 4000 });
      }
    });
  }

  // ── Métodos de Edición de Pedidos ──────────────────────────────────────────
  isSkuInEditingOrder(sku: string): boolean {
    return this.editOrderLines().some(l => l.sku === sku);
  }

  openEditOrderForm(wo: WorkOrder): void {
    this.showNewOrderForm.set(false);
    this.editingOrder.set(wo);
    this.editOrderError.set('');
    this.editSelectedOperario.set(wo.assigned_operario_email || '');
    this.editSelectedStatus.set(wo.status);
    this.editSkuSearch.set('');

    this.loadOperarios();
    this.loadInventory();

    const lines: EditOrderLine[] = (wo.items || []).map(item => {
      const prod = this.products().find(p => p.sku === item.sku);
      const available = (prod ? prod.available_qty : 0) + item.quantity;
      const price = item.unit_price ?? (prod ? Number(prod.unit_price) : 0);
      return {
        sku: item.sku,
        product_name: item.product_name || (prod ? prod.product_name : item.sku),
        available_qty: available,
        quantity: item.quantity,
        unit_price: price,
      };
    });
    this.editOrderLines.set(lines);
  }

  cancelEditOrder(): void {
    this.editingOrder.set(null);
    this.editOrderError.set('');
    this.editOrderLines.set([]);
  }

  onEditOperarioChange(email: string): void {
    this.editSelectedOperario.set(email);
    const currentStatus = this.editSelectedStatus();

    // Regla: si estaba por_asignar y se selecciona operario -> pasa a pending
    if ((currentStatus === 'por_asignar' || !currentStatus) && email) {
      this.editSelectedStatus.set('pending');
    }
    // Regla: si estaba pending y se remueve operario -> vuelve a por_asignar
    else if (currentStatus === 'pending' && !email) {
      this.editSelectedStatus.set('por_asignar');
    }
    // Si estaba en otro estado (in_preparation, dispatched, etc.), conservar
  }

  addEditLineFromProduct(product: ProductInventory): void {
    const existing = this.editOrderLines().find(l => l.sku === product.sku);
    if (existing) {
      if (existing.quantity < existing.available_qty) {
        this.updateEditLineQty(product.sku, existing.quantity + 1);
      } else {
        this.snackBar.open(`No hay más stock disponible para ${product.sku}`, '', { duration: 2500 });
      }
    } else {
      if (product.available_qty <= 0) {
        this.snackBar.open(`${product.sku} no tiene stock disponible para agregar.`, 'Cerrar', { duration: 2500 });
        return;
      }
      this.editOrderLines.update(lines => [
        ...lines,
        {
          sku: product.sku,
          product_name: product.product_name,
          available_qty: product.available_qty,
          quantity: 1,
          unit_price: Number(product.unit_price) || 0,
        }
      ]);
    }
    this.editSkuSearch.set('');
  }

  updateEditLineQty(sku: string, qty: number): void {
    this.editOrderLines.update(lines =>
      lines.map(l => {
        if (l.sku !== sku) return l;
        const clamped = Math.max(1, Math.min(qty, l.available_qty));
        return { ...l, quantity: clamped };
      })
    );
  }

  removeEditLine(sku: string): void {
    this.editOrderLines.update(lines => lines.filter(l => l.sku !== sku));
  }

  getEditTotalItems(): number {
    return this.editOrderLines().reduce((sum, l) => sum + l.quantity, 0);
  }

  getEditTotalAmount(): number {
    return this.editOrderLines().reduce((sum, l) => sum + (l.quantity * (l.unit_price || 0)), 0);
  }

  saveEditOrder(): void {
    const wo = this.editingOrder();
    if (!wo) return;

    const lines = this.editOrderLines();
    if (lines.length === 0) {
      this.editOrderError.set('El pedido debe tener al menos un producto.');
      this.snackBar.open('El pedido debe tener al menos un producto.', '', { duration: 3000 });
      return;
    }
    const invalid = lines.find(l => l.quantity < 1);
    if (invalid) {
      this.editOrderError.set(`Cantidad inválida para ${invalid.sku}.`);
      this.snackBar.open(`Cantidad inválida para ${invalid.sku}.`, '', { duration: 3000 });
      return;
    }

    const overStock = lines.find(l => l.quantity > l.available_qty);
    if (overStock) {
      this.editOrderError.set(`Stock insuficiente para ${overStock.sku}: disponible ${overStock.available_qty}, solicitado ${overStock.quantity}.`);
      this.snackBar.open(`Stock insuficiente para ${overStock.sku}.`, '', { duration: 4000 });
      return;
    }

    this.savingEditOrder.set(true);
    this.editOrderError.set('');

    const op = this.operarios().find(o => o.email === this.editSelectedOperario());
    const payload: WorkOrderUpdate = {
      status: this.editSelectedStatus(),
      assigned_operario_id: op ? op.id : null,
      assigned_operario_email: op ? op.email : null,
      items: lines.map(l => ({ sku: l.sku, quantity: l.quantity })),
    };

    this.workOrdersService.updateWorkOrder(wo.id, payload).subscribe({
      next: updated => {
        this.workOrders.update(wos => wos.map(w => w.id === updated.id ? updated : w));
        this.editingOrder.set(null);
        this.savingEditOrder.set(false);
        this.snackBar.open(`✅ Pedido ${updated.order_number} actualizado con éxito`, 'OK', { duration: 4000 });
        this.loadInventory();
      },
      error: err => {
        this.savingEditOrder.set(false);
        const msg = err.error?.detail ?? 'Error al actualizar el pedido';
        // Se conserva el formulario y los datos para evitar que se pierdan
        this.editOrderError.set(msg);
        this.snackBar.open(`❌ ${msg}`, 'Cerrar', { duration: 5000 });
      },
    });
  }

  // ── Recepciones ────────────────────────────────────────────────────────────
  loadReceptions(): void {
    this.receptionsLoading.set(true);
    this.inventoryService.getReceptions().subscribe({
      next: recs => { this.receptions.set(recs); this.receptionsLoading.set(false); },
      error: () => this.receptionsLoading.set(false),
    });
  }

  createReception(): void {
    const r = this.newReception();
    if (!r.sku || r.expected_quantity <= 0) {
      this.snackBar.open('SKU y cantidad válida requeridos.', '', { duration: 3000 });
      return;
    }
    this.inventoryService.createReception(r).subscribe({
      next: created => {
        this.receptions.update(list => [created, ...list]);
        this.showNewReceptionForm.set(false);
        this.newReception.set({ sku: '', expected_quantity: 0, notes: '' });
        this.snackBar.open(`Recepción registrada`, 'OK', { duration: 3000 });
        this.loadInventory();
      },
      error: err => this.snackBar.open(err.error?.detail ?? 'Error al crear', 'Cerrar', { duration: 4000 })
    });
  }

  confirmReceptionArrival(rec: PendingReception): void {
    this.editingReception.set(null);
    this.showNewReceptionForm.set(false);
    this.confirmingReception.set(rec);
    const remaining = Math.max(0, rec.expected_quantity - rec.received_quantity);
    this.confirmQty.set(remaining);
    this.confirmCloseShortage.set(false);
    this.confirmNotes.set(rec.notes ?? '');
  }

  cancelConfirmReception(): void {
    this.confirmingReception.set(null);
  }

  submitConfirmReception(): void {
    const rec = this.confirmingReception();
    if (!rec) return;
    const qtyNum = Number(this.confirmQty());
    if (isNaN(qtyNum) || qtyNum < 0) {
      this.snackBar.open('Ingresa una cantidad recibida válida (>= 0).', 'Cerrar', { duration: 3000 });
      return;
    }

    this.savingReceptionAction.set(true);
    this.inventoryService
      .confirmReception(rec.id, qtyNum, this.confirmCloseShortage(), this.confirmNotes())
      .subscribe({
        next: updated => {
          this.receptions.update(list => list.map(r => r.id === updated.id ? updated : r));
          this.confirmingReception.set(null);
          this.savingReceptionAction.set(false);
          this.snackBar.open(
            updated.status === 'completed'
              ? `✅ Recepción #${updated.id} completada (${updated.received_quantity}/${updated.expected_quantity})`
              : `📦 Llegada parcial registrada para ${updated.sku} (${updated.received_quantity}/${updated.expected_quantity})`,
            'OK',
            { duration: 3500 }
          );
          this.loadInventory();
          this.loadWorkOrders();
        },
        error: err => {
          this.savingReceptionAction.set(false);
          this.snackBar.open(err.error?.detail ?? 'Error al confirmar recepción', 'Cerrar', { duration: 4000 });
        },
      });
  }

  openEditReception(rec: PendingReception): void {
    this.confirmingReception.set(null);
    this.showNewReceptionForm.set(false);
    this.editingReception.set(rec);
    this.editReceptionExpected.set(rec.expected_quantity);
    this.editReceptionReceived.set(rec.received_quantity);
    this.editReceptionNotes.set(rec.notes ?? '');
  }

  cancelEditReception(): void {
    this.editingReception.set(null);
  }

  submitEditReception(): void {
    const rec = this.editingReception();
    if (!rec) return;
    const expected = Number(this.editReceptionExpected());
    const received = Number(this.editReceptionReceived());
    if (isNaN(expected) || expected <= 0) {
      this.snackBar.open('La cantidad esperada debe ser mayor a 0.', 'Cerrar', { duration: 3000 });
      return;
    }
    if (isNaN(received) || received < 0) {
      this.snackBar.open('La cantidad recibida debe ser 0 o mayor.', 'Cerrar', { duration: 3000 });
      return;
    }

    this.savingReceptionAction.set(true);
    this.inventoryService
      .updateReception(rec.id, {
        expected_quantity: expected,
        received_quantity: received,
        notes: this.editReceptionNotes(),
      })
      .subscribe({
        next: updated => {
          this.receptions.update(list => list.map(r => r.id === updated.id ? updated : r));
          this.editingReception.set(null);
          this.savingReceptionAction.set(false);
          this.snackBar.open(`✅ Recepción #${updated.id} actualizada`, 'OK', { duration: 3500 });
          this.loadInventory();
          this.loadWorkOrders();
        },
        error: err => {
          this.savingReceptionAction.set(false);
          this.snackBar.open(err.error?.detail ?? 'Error al editar recepción', 'Cerrar', { duration: 4000 });
        },
      });
  }

  cancelReception(rec: PendingReception): void {
    const remaining = Math.max(0, rec.expected_quantity - rec.received_quantity);
    const ok = confirm(
      `¿Cancelar la recepción #${rec.id} (${rec.sku})?\n\n` +
      `Se liberarán ${remaining} unidad(es) de "por llegar" en el inventario.`
    );
    if (!ok) return;

    this.savingReceptionAction.set(true);
    this.inventoryService.cancelReception(rec.id).subscribe({
      next: updated => {
        this.receptions.update(list => list.map(r => r.id === updated.id ? updated : r));
        if (this.editingReception()?.id === rec.id) this.editingReception.set(null);
        if (this.confirmingReception()?.id === rec.id) this.confirmingReception.set(null);
        this.savingReceptionAction.set(false);
        this.snackBar.open(`❌ Recepción #${updated.id} cancelada`, 'OK', { duration: 3500 });
        this.loadInventory();
      },
      error: err => {
        this.savingReceptionAction.set(false);
        this.snackBar.open(err.error?.detail ?? 'Error al cancelar recepción', 'Cerrar', { duration: 4000 });
      },
    });
  }

  getReceptionStatusLabel(status: string): string {
    const map: Record<string, string> = {
      pending: 'Pendiente',
      partial: 'Parcial',
      completed: 'Completada',
      cancelled: 'Cancelada',
    };
    return map[(status || '').toLowerCase()] ?? status;
  }

  // ── Helpers de UI ──────────────────────────────────────────────────────────
  getOrderStatusClass(status: string): string {
    const map: Record<string, string> = {
      completed: 'chip-success',
      received: 'chip-info',
      processing: 'chip-warning',
      rejected: 'chip-danger',
      failed: 'chip-danger',
      cancelled: 'chip-muted',
    };
    return map[(status || '').toLowerCase()] ?? 'chip-muted';
  }

  getOrderStatusLabel(status: string): string {
    const map: Record<string, string> = {
      received: 'Recibido',
      processing: 'En proceso',
      completed: 'Completado',
      rejected: 'Rechazado',
      failed: 'Fallido',
      cancelled: 'Cancelado',
    };
    return map[(status || '').toLowerCase()] ?? status;
  }

  isOrderPaid(order: Order): boolean {
    const ps = (order.payment_status || '').toLowerCase().trim();
    return ps === 'paid' || ps === 'pagado' || ps === 'confirmed';
  }

  getPaymentStatusLabel(order: Order): string {
    return this.isOrderPaid(order) ? 'Pagado' : 'Pago pendiente';
  }

  getPaymentStatusClass(order: Order): string {
    return this.isOrderPaid(order) ? 'chip-success' : 'chip-warning';
  }

  getWoStatusClass(status: string): string {
    const s = (status || '').toLowerCase();
    const map: Record<string, string> = {
      por_asignar: 'chip-info',
      pending: 'chip-warning',
      assigned: 'chip-warning',
      in_preparation: 'chip-primary',
      in_progress: 'chip-primary',
      dispatched: 'chip-success',
      completed: 'chip-success',
      cancelled: 'chip-muted',
      waiting_stock: 'chip-danger',
    };
    return map[s] ?? 'chip-muted';
  }

  getWoStatusLabel(status: string): string {
    const s = (status || '').toLowerCase();
    const map: Record<string, string> = {
      por_asignar: 'Por asignar',
      pending: 'Pendiente',
      assigned: 'Asignado',
      in_preparation: 'En preparación',
      in_progress: 'En proceso',
      dispatched: 'Despachado',
      completed: 'Finalizado',
      cancelled: 'Cancelado',
      waiting_stock: 'Esperando stock',
    };
    return map[s] ?? status;
  }

  getTotalItems(wo: WorkOrder): number {
    if (wo.total_items !== undefined && wo.total_items !== null) return wo.total_items;
    return (wo.items || []).reduce((sum, it) => sum + it.quantity, 0);
  }

  getTotalAmount(wo: WorkOrder): number {
    if (wo.total_amount !== undefined && wo.total_amount !== null) return wo.total_amount;
    return (wo.items || []).reduce((sum, it) => sum + ((it.subtotal || 0) || (it.quantity * (it.unit_price || 0))), 0);
  }

  getItemsTooltip(wo: WorkOrder): string {
    return (wo.items || []).map(it => `${it.sku}: ${it.quantity} uds (${it.product_name})`).join('\n');
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
