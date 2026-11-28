# SmartWMS — Sistema Integral de Gestión de Bodega y Logística

SmartWMS es una plataforma WMS full-stack para gestión de inventario, recepción de órdenes, armado y despacho de pedidos, layout físico de almacén y asistencia operativa con IA, desplegada en **Google Cloud Platform (Cloud Run + Cloud SQL PostgreSQL)** con CI/CD automático desde GitHub.

## Arquitectura y Servicios en Producción (GCP — Cloud Run + Cloud SQL)

| Componente | Tecnología | Entorno / Servicio | Descripción |
| :--- | :--- | :--- | :--- |
| **Frontend Web** | Angular 22 (Zoneless + Nginx) | Cloud Run (`smartwms-frontend`) | Paneles de Supervisor y Operario, Layout interactivo, QR/Code 128, Pedidos, Recepciones y Copiloto IA con Markdown |
| **Backend API** | FastAPI + SQLAlchemy | Cloud Run (`smartwms-backend`) | API REST, JWT + MFA TOTP, Webhooks de órdenes, control de stock atómico y endpoints de Layout/Putaway |
| **Bot IA** | FastAPI + Gemini API | Cloud Run (`smartwms-bot`) | Copiloto inteligente para consultas operativas con soporte completo de Markdown |
| **Base de Datos** | Cloud SQL (`POSTGRES_18`) | Cloud SQL | Fuente única de verdad persistente para inventario, órdenes, pedidos, recepciones y ubicaciones |
| **App Móvil Android** | Kotlin Nativo (`android-operario`) | Flavor `production` | App de picking, packing, escáner QR/Barras (`Code 128`) y módulo Putaway en tiempo real |

## Funcionalidades Principales Implementadas

- **Autenticación y Seguridad:** JWT + MFA obligatorio (TOTP) con recuperación, control de presencia en línea de operarios y aislamiento de visibilidad de usuarios por rol.
- **Órdenes y Pedidos de Bodega:** Recepción de órdenes pagadas via webhook (`POST /api/v1/webhooks/orders`) sin descuento anticipado de stock; carga directa de productos a pedido validando stock disponible real; reserva en pedidos y descuento físico atómico (`SELECT FOR UPDATE`) únicamente al despachar; gestión de estados confirmables (`Recibido`, `En proceso`, `Completado`, `Rechazado`).
- **Inventario, Códigos QR / Barras y Recepciones:** Generación determinista de QR estándar (`segno`) y código de barras **Code 128** por SKU; gestión de recepciones esperadas con entrega parcial, edición de cantidades reales/dañadas, cierre por faltante y cancelación.
- **Layout Dinámico y Módulo Putaway (Supervisor + APK):**
  - 4 mesas predeterminadas (`M-01`..`M-04`) más administración completa de mesas, zonas y estanterías.
  - Consulta en vivo del contenido y fecha de almacenamiento de cada ubicación.
  - Putaway en APK Android con autocompletado de SKUs, escáner QR/Barras, almacenamiento inicial o traslado entre ubicaciones sin duplicar stock y trazabilidad de movimientos.
- **Despliegue Automático (CI/CD):** Cada `git push` a `main` dispara Cloud Build ([APP/deploy/gcp/cloudbuild.yaml](deploy/gcp/cloudbuild.yaml)) para compilar y actualizar automáticamente los 3 servicios en Cloud Run.

---

## Estructura del Repositorio

```text
SmartWMS/
├── Fase 1/                                 # Documentación y entregables Fase 1
├── Fase 2/                                 # Documentación y entregables Fase 2
├── Fase 3/                                 # Documentación y entregables Fase 3
└── APP/                                    # Código fuente, despliegue y utilidades de la aplicación
    ├── android-operario/                   # App móvil nativa Android (Kotlin)
    ├── bot/                                # Servicio Bot IA (FastAPI + Gemini)
    ├── deploy/gcp/                         # Pipeline CI/CD (cloudbuild.yaml) y script manual de aprovisionamiento
    ├── ecommerce/
    │   ├── backend/                        # API REST FastAPI, modelos SQLAlchemy, tests y simulador webhook
    │   └── frontend/smartwms-angular/      # Portal web Angular + Nginx para Cloud Run
    ├── scripts/                            # Utilidades administrativas (init_db, reset_user_mfa) y pruebas
    └── README.md                           # Documentación técnica de la aplicación
```

---

## Despliegue en la Nube (CI/CD)

1. Los servicios `smartwms-bot`, `smartwms-backend` y `smartwms-frontend` se compilan mediante sus respectivos `Dockerfile` y se actualizan automáticamente en Cloud Run al hacer push a `main` usando [APP/deploy/gcp/cloudbuild.yaml](deploy/gcp/cloudbuild.yaml).
2. Las variables sensibles (`JWT_SECRET`, credenciales de Cloud SQL, `WEBHOOK_SECRET`, claves de Gemini, `MFA_REQUIRED_ROLES`) se administran directamente en **Cloud Run** y **Secret Manager**.
3. Como respaldo ante una recreación desde cero de infraestructura GCP, se conserva [APP/deploy/gcp/deploy-gcp.ps1](deploy/gcp/deploy-gcp.ps1).

---

## Compilación de la App Móvil Android (`APP/android-operario`)

Para generar el APK apuntando al entorno de producción en Cloud Run:

```bash
cd APP/android-operario
.\gradlew assembleProductionDebug
```

El APK compilado listo para instalar se encuentra en `APP/android-operario/apk/SmartWMS-Operario-production.apk` (y la salida directa de Gradle en `APP/android-operario/app/build/outputs/apk/production/debug/app-production-debug.apk`). Desde la pantalla de inicio de sesión también es posible ajustar la URL del servidor si se requiere apuntar a otro entorno.

---

## Utilidades y Pruebas de Desarrollo

- **Pruebas del backend:** `APP/ecommerce/backend/test_mfa.py`, `test_phase5.py`, `test_scenarios.py`, `test_security_and_acid.py` y `APP/scripts/test_*.py`.
- **Simulador de webhooks de e-commerce:**
  ```bash
  python APP/ecommerce/backend/webhook_simulator.py --url <URL_BACKEND>/api/v1/webhooks/orders
  ```
- **Administración CLI (usando `DATABASE_URL` o Cloud SQL Auth Proxy):**
  - `python APP/scripts/init_db.py` — Verifica/inicializa tablas y datos base si la BD está vacía.
  - `python APP/scripts/reset_user_mfa.py --list` — Lista o resetea MFA de usuarios.
  - `python APP/ecommerce/backend/db_viewer.py` — Inspección rápida de tablas en consola.
