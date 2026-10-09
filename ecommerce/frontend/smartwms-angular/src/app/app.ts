import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Componente raíz de SmartWMS Angular.
 * Solo actúa como shell — toda la UI vive en las feature routes.
 */
@Component({
  imports: [RouterOutlet],
  selector: 'app-root',
  template: '<router-outlet />',
  styleUrl: './app.scss',
})
export class App {
  title = 'SmartWMS E-Commerce';
}
