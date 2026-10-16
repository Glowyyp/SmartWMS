// features/inventory/inventory.component.ts
// Vista del inventario de productos con tabla filtrable y estado de stock

import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';

// Angular Material
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatTableModule } from '@angular/material/table';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatChipsModule } from '@angular/material/chips';
import { MatBadgeModule } from '@angular/material/badge';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { InventoryService, ProductInventory, PendingReception } from '../../core/services/inventory.service';
import { AuthService } from '../../core/services/auth.service';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';

@Component({
  selector: 'app-inventory',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    FormsModule,
    MatCardModule,
    MatIconModule,
    MatButtonModule,
    MatToolbarModule,
    MatTableModule,
    MatInputModule,
    MatFormFieldModule,
    MatChipsModule,
    MatBadgeModule,
    MatTooltipModule,
    MatProgressBarModule,
    MatDialogModule
  ],
  templateUrl: './inventory.component.html',
  styleUrls: ['./inventory.component.scss'],
})
export class InventoryComponent implements OnInit {
  displayedColumns = ['sku', 'product_name', 'available_qty', 'reserved_qty', 'pending_quantity', 'dimensions', 'status'];

  searchQuery = signal('');

  allProducts = signal<ProductInventory[]>([]);

  filteredProducts = computed(() => {
    const q = this.searchQuery().toLowerCase();
    const products = this.allProducts();
    if (!q) return products;
    return products.filter(
      (p) => p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)
    );
  });

  get lowStockCount(): number {
    return this.allProducts().filter((p) => p.available_qty <= p.reorder_point).length;
  }

  constructor(
    private authService: AuthService,
    private inventoryService: InventoryService,
    private dialog: MatDialog
  ) {}

  ngOnInit(): void {
    this.loadProducts();
  }

  loadProducts(): void {
    this.inventoryService.getProducts().subscribe((data) => {
      this.allProducts.set(data);
    });
  }

  getStockStatus(product: ProductInventory): 'critical' | 'warning' | 'ok' {
    const ratio = product.available_qty / product.reorder_point;
    if (product.available_qty <= 0) return 'critical';
    if (ratio <= 1)  return 'critical';
    if (ratio <= 2)  return 'warning';
    return 'ok';
  }

  getStockProgress(product: ProductInventory): number {
    const max = product.reorder_point * 5;
    return Math.min((product.available_qty / max) * 100, 100);
  }

  logout(): void {
    this.authService.logout();
  }
}
