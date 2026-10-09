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

import { AuthService } from '../../core/services/auth.service';

interface Product {
  sku: string;
  product_name: string;
  stock_quantity: number;
  unit_price: number;
  reorder_point: number;
}

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
  ],
  templateUrl: './inventory.component.html',
  styleUrls: ['./inventory.component.scss'],
})
export class InventoryComponent implements OnInit {
  displayedColumns = ['sku', 'product_name', 'stock_quantity', 'unit_price', 'reorder_point', 'status'];

  searchQuery = signal('');

  // Productos de muestra (en producción vendrían de InventoryService)
  allProducts: Product[] = [
    { sku: 'SKU-00567', product_name: 'Teclado Mecánico RGB',    stock_quantity: 145, unit_price: 29.99,  reorder_point: 20  },
    { sku: 'SKU-00412', product_name: 'Tornillo M8 Acero',       stock_quantity: 3,   unit_price: 0.50,   reorder_point: 100 },
    { sku: 'SKU-00891', product_name: 'Cable USB-C 2m',           stock_quantity: 80,  unit_price: 14.99,  reorder_point: 15  },
    { sku: 'SKU-01234', product_name: 'Monitor 27" 144Hz',        stock_quantity: 12,  unit_price: 399.99, reorder_point: 5   },
    { sku: 'SKU-01567', product_name: 'Mousepad XL Gaming',       stock_quantity: 200, unit_price: 19.99,  reorder_point: 30  },
    { sku: 'SKU-01890', product_name: 'Auriculares Inalámbricos', stock_quantity: 8,   unit_price: 89.99,  reorder_point: 10  },
  ];

  filteredProducts = computed(() => {
    const q = this.searchQuery().toLowerCase();
    if (!q) return this.allProducts;
    return this.allProducts.filter(
      (p) => p.sku.toLowerCase().includes(q) || p.product_name.toLowerCase().includes(q)
    );
  });

  get lowStockCount(): number {
    return this.allProducts.filter((p) => p.stock_quantity <= p.reorder_point).length;
  }

  constructor(private authService: AuthService) {}
  ngOnInit(): void {}

  getStockStatus(product: Product): 'critical' | 'warning' | 'ok' {
    const ratio = product.stock_quantity / product.reorder_point;
    if (product.stock_quantity === 0) return 'critical';
    if (ratio <= 1)  return 'critical';
    if (ratio <= 2)  return 'warning';
    return 'ok';
  }

  getStockProgress(product: Product): number {
    const max = product.reorder_point * 5;
    return Math.min((product.stock_quantity / max) * 100, 100);
  }

  logout(): void {
    this.authService.logout();
  }
}
