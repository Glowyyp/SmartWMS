// features/operario/operario.component.ts
// Panel del Operario de Bodega — SmartWMS

import { Component, OnInit, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { AuthService } from '../../core/services/auth.service';
import { ChatbotComponent } from '../../shared/chatbot/chatbot.component';
import { WorkOrdersService, WorkOrder } from '../../core/services/work-orders.service';
import { InventoryService, ProductInventory } from '../../core/services/inventory.service';
import { Subscription, interval, forkJoin } from 'rxjs';
import { startWith, switchMap } from 'rxjs/operators';

type Task = 'dispatch' | 'putaway';

interface PutawayForm {
  sku: string;
  quantity: number | null;
  location: string;
}

@Component({
  selector: 'app-operario',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MatIconModule, MatButtonModule, MatProgressBarModule,
    MatTooltipModule, MatSnackBarModule,
    ChatbotComponent,
  ],
  templateUrl: './operario.component.html',
  styleUrls: ['./operario.component.scss'],
})
export class OperarioComponent implements OnInit, OnDestroy {
  activeTask = signal<Task>('dispatch');

  // ── DESPACHO DE PEDIDOS ───────────────────────────────────────────────────
  pendingOrders = signal<WorkOrder[]>([]);
  loadingOrders = signal(false);
  ordersError = signal('');
  selectedOrder = signal<WorkOrder | null>(null);
  dispatching = signal(false);

  // ── Bultos ────────────────────────────────────────────────────────────────
  packages = signal<any[]>([]);
  newPackage = signal({ length: null, width: null, height: null, weight: null });

  // ── INVENTARIO (para localización de SKUs) ────────────────────────────────
  private inventoryMap = signal<Record<string, ProductInventory>>({});

  // ── MODAL LOCALIZACIÓN ────────────────────────────────────────────────────
  locationModal = signal<{ sku: string; location: string | null } | null>(null);

  // ── PUTAWAY ──────────────────────────────────────────────────────────────
  putawayForm = signal<PutawayForm>({ sku: '', quantity: null, location: '' });
  putawaySuccess = signal(false);
  putawayError = signal('');
  validLocations = ['A-01-A','A-01-B','A-02-A','A-03-B','B-01-A','B-02-C','C-01-A','C-02-B','C-03-B','D-01-A'];

  private pollSub?: Subscription;
  private currentUserEmail = '';

  constructor(
    private authService: AuthService,
    private workOrdersService: WorkOrdersService,
    private inventoryService: InventoryService,
    private snackBar: MatSnackBar,
  ) {}

  ngOnInit(): void {
    this.currentUserEmail = this.authService.getEmail() ?? '';

    // Cargar inventario para tener las ubicaciones disponibles
    this.inventoryService.getProducts().subscribe({
      next: products => {
        const map: Record<string, ProductInventory> = {};
        products.forEach(p => map[p.sku] = p);
        this.inventoryMap.set(map);
      },
    });

    // Poll pedidos pendientes asignados a ESTE operario cada 15s
    // Se usa assigned_to=email para filtrar solo los pedidos de este operario
    this.pollSub = interval(15000).pipe(
      startWith(0),
      switchMap(() => this.workOrdersService.getWorkOrders('pending,in_preparation,in_progress', this.currentUserEmail))
    ).subscribe({
      next: orders => {
        this.pendingOrders.set(orders);
        this.loadingOrders.set(false);
        // Si el pedido seleccionado ya fue despachado/cancelado, deseleccionar
        const sel = this.selectedOrder();
        if (sel) {
          const updated = orders.find(o => o.id === sel.id);
          if (!updated) this.selectedOrder.set(null);
        }
      },
      error: () => { this.ordersError.set('Error al cargar pedidos.'); this.loadingOrders.set(false); },
    });
    this.loadingOrders.set(true);
  }

  ngOnDestroy(): void {
    this.pollSub?.unsubscribe();
  }

  // ── LOCALIZACIÓN DE SKU ───────────────────────────────────────────────────

  /**
   * Obtiene la ubicación física de un SKU a partir del inventario.
   * Fuente única de verdad: campo warehouse_location de ProductInventory.
   */
  getSkuLocation(sku: string): string | null {
    const product = this.inventoryMap()[sku];
    return product?.warehouse_location ?? null;
  }

  showLocationModal(sku: string): void {
    const location = this.getSkuLocation(sku);
    this.locationModal.set({ sku, location });
  }

  closeLocationModal(): void {
    this.locationModal.set(null);
  }

  // ── DESPACHO ──────────────────────────────────────────────────────────────
  selectOrder(order: WorkOrder): void {
    this.selectedOrder.set(order);
  }

  backToList(): void {
    this.selectedOrder.set(null);
  }

  confirmDispatch(): void {
    const order = this.selectedOrder();
    if (!order) return;

    if (!confirm(`¿Confirmar despacho del pedido ${order.order_number}?\nEsta acción descontará el stock físico y no puede deshacerse.`)) return;

    this.dispatching.set(true);

    let totalWeight = 0;
    let totalVolume = 0;
    const pkgs = this.packages();
    for (const p of pkgs) {
      if (p.weight) totalWeight += Number(p.weight);
      if (p.length && p.width && p.height) {
        totalVolume += (Number(p.length) * Number(p.width) * Number(p.height));
      }
    }

    const payload = pkgs.length > 0 ? {
      packages: pkgs,
      total_weight: totalWeight,
      total_volume: totalVolume
    } : undefined;

    this.workOrdersService.dispatch(order.id, payload).subscribe({
      next: dispatched => {
        this.dispatching.set(false);
        this.selectedOrder.set(dispatched);  // Mostrar estado despachado
        // Remover de la lista de pendientes
        this.pendingOrders.update(orders => orders.filter(o => o.id !== dispatched.id));
        this.packages.set([]);
        this.newPackage.set({ length: null, width: null, height: null, weight: null });
        this.snackBar.open(
          `✅ Pedido ${dispatched.order_number} despachado. Stock actualizado.`,
          'OK',
          { duration: 5000, panelClass: ['success-snack'] }
        );
      },
      error: err => {
        this.dispatching.set(false);
        const msg = err.error?.detail ?? 'Error al despachar. Intenta nuevamente.';
        this.snackBar.open(msg, 'Cerrar', { duration: 6000 });
      },
    });
  }

  addPackage(): void {
    const p = this.newPackage();
    if (p.weight || (p.length && p.width && p.height)) {
      this.packages.update(list => [...list, { ...p }]);
      this.newPackage.set({ length: null, width: null, height: null, weight: null });
    } else {
      this.snackBar.open('Complete las medidas o el peso', '', { duration: 2000 });
    }
  }

  removePackage(index: number): void {
    this.packages.update(list => list.filter((_, i) => i !== index));
  }

  // ── PUTAWAY ───────────────────────────────────────────────────────────────
  updatePutaway(field: keyof PutawayForm, value: string | number): void {
    this.putawayForm.update(f => ({ ...f, [field]: value }));
  }

  submitPutaway(): void {
    const form = this.putawayForm();
    this.putawayError.set('');
    if (!form.sku.trim()) { this.putawayError.set('El SKU es requerido.'); return; }
    if (!form.quantity || form.quantity < 1) { this.putawayError.set('La cantidad debe ser mayor a 0.'); return; }
    if (!this.validLocations.includes(form.location)) {
      this.putawayError.set(`Ubicación inválida. Use: ${this.validLocations.slice(0,4).join(', ')}...`);
      return;
    }
    this.putawaySuccess.set(true);
    this.snackBar.open(`Almacenado: ${form.sku} → ${form.location}`, 'OK', { duration: 3000 });
    setTimeout(() => {
      this.putawaySuccess.set(false);
      this.putawayForm.set({ sku: '', quantity: null, location: '' });
    }, 2500);
  }

  logout(): void { this.authService.logout(); }
}
