// app.config.ts — Configuración central de la aplicación Angular (standalone)
// Reemplaza el NgModule raíz con la API funcional de Angular 17+

import { ApplicationConfig, provideZonelessChangeDetection } from '@angular/core';
import { provideRouter, withViewTransitions } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

import { routes } from './app.routes';
import { authInterceptor } from './core/interceptors/auth.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    // Detección de cambios zoneless (Angular 22 sin zone.js)
    provideZonelessChangeDetection(),

    // Router con transiciones de vista nativas (View Transitions API)
    provideRouter(routes, withViewTransitions()),

    // HTTP client con el interceptor JWT inyectado automáticamente
    provideHttpClient(withInterceptors([authInterceptor])),

    // Animaciones de Angular Material (lazy por defecto en v17+)
    provideAnimationsAsync(),
  ],
};
