# SmartWMS - Sistema de Gestión de Almacén y Logística

SmartWMS es una plataforma integral de gestión de bodega y despachos compuesta por:
1. **Backend API (FastAPI - Puerto 8001):** Motor central con autenticación JWT, WebSockets en tiempo real (`/ws/orders`), auditoría inmutable de pedidos y control de inventario.
2. **Bot IA y Copiloto (FastAPI - Puerto 8000):** Servicio de asistencia inteligente para consultas operativas y automatización de procesos.
3. **Frontend Web (Angular 18+ - Puerto 4200):** Aplicación web reactiva con portales dedicados para **Supervisor** (`/supervisor`) y **Operario** (`/operario`).
4. **App Móvil Android (Kotlin Nativo):** Aplicación de picking y despacho para dispositivos móviles y terminales de mano con escáner de códigos de barras.
5. **Base de Datos Centralizada (SQLite / `ecommerce.db`):** Fuente única de verdad persistente para todas las aplicaciones.

---

## 1. Requisitos Previos en el Nuevo PC

Para ejecutar SmartWMS en un equipo nuevo con Windows 10/11 se requiere:

- **Python 3.10 o superior:** [Descargar Python](https://www.python.org/downloads/)
  > *Importante:* Al instalar Python, marcar obligatoriamente la casilla **"Add python.exe to PATH"**.
- **Node.js LTS (v18 o v20):** [Descargar Node.js LTS](https://nodejs.org/)
  > Se instalará automáticamente `npm`.
- **Git para Windows:** [Descargar Git](https://git-scm.com/download/win)
- **(Opcional para compilar la App Android):** Android Studio Jellyfish/Koala con JDK 17 o superior. *Si solo se instala el APK generado en el celular, no es necesario instalar Android Studio en el PC servidor.*

---

## 2. Instalación Rápida desde Git (Entorno Limpio)

Sigue estos sencillos pasos para clonar y preparar el proyecto:

```bash
# 1. Clonar el repositorio
git clone <URL_DEL_REPOSITORIO_GIT> SmartWMS
cd SmartWMS

# 2. Ejecutar el instalador automático
instalar.bat
```

### ¿Qué hace `instalar.bat` automáticamente?
1. Verifica que Python y Node.js estén instalados y disponibles en el PATH.
2. Crea el archivo `.env` local a partir de la plantilla `.env.example` si no existe.
3. Instala todas las dependencias de Python del Backend (`ecommerce/backend/requirements.txt`) y del Bot (`bot/requirements.txt`).
4. Instala todas las dependencias de Angular (`npm install`).
5. Ejecuta `scripts/init_db.py` para crear las tablas y sembrar los usuarios iniciales e inventario demo si la base de datos está vacía.

---

## 3. Inicio y Control del Sistema con Scripts de Windows

No necesitas abrir múltiples consolas manualmente; utiliza los scripts incluidos en la raíz:

| Script | Descripción |
| :--- | :--- |
| `iniciar.bat` | Detecta la IP real de tu máquina, habilita los puertos en el firewall si es necesario, verifica puertos en uso y arranca el Backend (8001), Bot (8000) y Angular (4200) en consolas independientes. Muestra en pantalla las URLs de acceso y credenciales. |
| `detener.bat` | Detiene y cierra ordenadamente todos los procesos que estén escuchando en los puertos 8001, 8000 y 4200. |
| `estado.bat` | Ejecuta un diagnóstico inmediato de la salud del sistema, comprobando conectividad TCP y respuestas HTTP de cada servicio. |
| `instalar.bat` | Prepara dependencias, variables y base de datos desde cero. |

---

## 4. Configuración Centralizada y Cambio de IP (.env)

El archivo `.env` en la raíz del proyecto es el **único lugar** donde se configuran los parámetros del servidor.

### Variables Principales:
```ini
# IP o Nombre de Dominio del Servidor (0.0.0.0 permite escuchar en todas las interfaces de red)
SERVER_HOST=0.0.0.0
SERVER_PORT=8001
SERVER_IP=127.0.0.1  # Reemplazar con la IP local de tu PC o IP de Tailscale para dispositivos externos

# Puertos de Servicios
BOT_PORT=8000
FRONTEND_PORT=4200

# Base de Datos SQLite canónica
DATABASE_URL=sqlite:///./ecommerce.db

# Seguridad JWT
JWT_SECRET=tu_clave_secreta_aqui_reemplazar_en_produccion
```

### Detección Dinámica en Frontend y Backend:
- **Frontend Angular:** Está configurado para detectar automáticamente `window.location.hostname`. Si abres la web desde `http://192.168.1.5:4200`, el frontend se conectará automáticamente a la API en `http://192.168.1.5:8001` sin requerir recompilación de código.
- **Backend API:** Incorpora una política CORS permisiva para redes de desarrollo y producción local (`allow_origin_regex=r"^https?://.*"`), aceptando solicitudes desde cualquier dirección IP de la red local o VPN.

---

## 5. Base de Datos: Persistencia, Respaldos y Migración

SmartWMS utiliza una base de datos SQLite relacional canónica ubicada en la raíz del proyecto: `ecommerce.db`.

### Credenciales por Defecto
| Rol | Correo | Contraseña |
| :--- | :--- | :--- |
| **Supervisor** | `supervisor@smartwms.com` | `supervisor123` |
| **Operario** | `operario@smartwms.com` | `operario123` |
| **Administrador** | `admin@smartwms.com` | `admin123` |

### Herramienta de Respaldo y Restauración
Para no perder datos al cambiar de PC o antes de actualizar con Git:

```bash
# Crear un respaldo con fecha y hora actual (se guarda en la carpeta /backups)
python scripts\backup_restore.py backup

# Listar todos los respaldos disponibles
python scripts\backup_restore.py list

# Restaurar el respaldo más reciente
python scripts\backup_restore.py restore

# Restaurar un respaldo específico
python scripts\backup_restore.py restore backups\ecommerce_backup_20261014_214211.db
```

### Cómo trasladar la base de datos a otro computador:
1. En el PC original, ejecuta: `python scripts\backup_restore.py backup`.
2. Copia el archivo generado dentro de `backups/` al nuevo PC (por pendrive, red o almacenamiento seguro).
3. En el nuevo PC, ejecuta: `python scripts\backup_restore.py restore backups\<nombre_archivo>.db`.
4. ¡Listo! Todos los pedidos, bultos registrados, usuarios e inventario estarán disponibles.

---

## 6. Sincronización en Tiempo Real

SmartWMS sincroniza las aplicaciones en tiempo real mediante **WebSockets** centralizados:
- **Canal de Sincronización:** `ws://<SERVER_IP>:8001/ws/orders`
- **Flujo de Trabajo:**
  1. Cuando un operario o supervisor crea, cancela o modifica un pedido en la Web o la App Móvil, el Backend emite un evento WebSocket con el payload del pedido actualizado.
  2. Todas las pantallas abiertas del Supervisor y Operario reciben el evento instantáneamente y actualizan sus tablas sin necesidad de recargar la página.
  3. Si la conexión se interrumpe temporalmente, el cliente web y móvil se reconectan automáticamente y consultan el estado actual al recuperar el enlace.

---

## 7. Conexión de la Aplicación Móvil Android

La aplicación Android (`android-operario`) está diseñada para conectarse a cualquier servidor sin tener que recompilar el código fuente.

### Opción A: Configuración en Tiempo de Ejecución (Recomendada)
1. Instala el APK en el teléfono o emulador.
2. Abre la aplicación y en la pantalla de **Iniciar Sesión**, presiona el botón **⚙ Configurar Servidor (IP)**.
3. Introduce la IP de tu PC servidor, por ejemplo:
   - En la misma red WiFi: `http://192.168.1.5:8001`
   - En emulador de Android Studio: `http://10.0.2.2:8001`
   - Mediante VPN Tailscale: `http://100.x.y.z:8001`
4. Presiona **Guardar y Conectar**. La app guardará la dirección de forma persistente y se conectará inmediatamente.

### Opción B: Configuración en Tiempo de Compilación
Si deseas compilar un nuevo APK con la IP preconfigurada:
- Define la variable de entorno `SERVER_IP` o agrégala en `android-operario/gradle.properties`:
  ```properties
  SERVER_IP=192.168.1.5
  ```
- O compila con gradle:
  ```bash
  cd android-operario
  .\gradlew assembleDebug -PSERVER_IP=192.168.1.5
  ```

---

## 8. Guía de Red: Local vs Otra Ubicación

### Escenario A: Dispositivos en la Misma Red (Mismo Router / WiFi)
Ideal para operar dentro del mismo almacén, bodega u oficina.

1. **Obtener la IP del Servidor:** Ejecuta `iniciar.bat`. El script detectará automáticamente tu IP local (ejemplo: `192.168.1.5`). También puedes comprobarla ejecutando: `python scripts\get_ip.py`.
2. **Configurar Firewall de Windows:** `iniciar.bat` intenta abrir los puertos 8001, 8000 y 4200 automáticamente. Si tu usuario no tiene permisos de administrador, abre una consola de PowerShell como Administrador y ejecuta:
   ```powershell
   New-NetFirewallRule -DisplayName "SmartWMS" -Direction Inbound -LocalPort 8001,8000,4200 -Protocol TCP -Action Allow
   ```
3. **Acceso desde otros dispositivos:**
   - **PC de Supervisor/Operario (Navegador):** `http://192.168.1.5:4200`
   - **Móvil Android:** Ingresa `http://192.168.1.5:8001` en el botón de configuración de la app.

---

### Escenario B: Dispositivos en Redes Diferentes (Ubicaciones Remotas / Internet)
Si el servidor está en la oficina/almacén y deseas acceder desde tu casa u otra sucursal, **NO expongas tu router ni abras puertos hacia Internet de forma insegura**. Se recomiendan dos alternativas profesionales y gratuitas:

#### Alternativa 1: Tailscale Mesh VPN (Recomendada - Máxima Seguridad y Facilidad)
[Tailscale](https://tailscale.com/) crea una red privada virtual cifrada (punto a punto) basada en WireGuard con configuración cero.

1. Instala Tailscale en el PC Servidor y en los dispositivos clientes (otro PC o teléfono Android) e inicia sesión con la misma cuenta (Google, Microsoft, etc.).
2. Tailscale asignará a tu PC servidor una IP fija privada del rango `100.x.y.z` (por ejemplo: `100.85.12.34`).
3. En el PC cliente o móvil, accede a:
   - Web: `http://100.85.12.34:4200`
   - App Móvil: `http://100.85.12.34:8001`
4. **Ventajas:** Conexión cifrada de extremo a extremo, no requiere abrir puertos en el router, funciona a través de cualquier firewall o NAT móvil (4G/5G).

#### Alternativa 2: Cloudflare Tunnel (Para acceso web con dominio público HTTPS)
1. Descarga `cloudflared` en el PC Servidor.
2. Crea un túnel seguro hacia `localhost:4200` (Web) y `localhost:8001` (Backend).
3. Obtendrás una URL pública segura como `https://smartwms.tudominio.com`.

---

## 9. Actualizaciones Futuras con Git

Para actualizar el proyecto desde Git en el nuevo PC sin perder configuraciones ni la base de datos:

1. **Crear siempre un respaldo antes de actualizar:**
   ```bash
   python scripts\backup_restore.py backup
   ```
2. **Descargar los cambios del repositorio:**
   ```bash
   git pull origin main
   ```
   *Nota: Tus archivos `.env` y `ecommerce.db` están excluidos en `.gitignore`, por lo que nunca serán sobrescritos por Git.*
3. **Actualizar dependencias:**
   ```bash
   python -m pip install -r ecommerce\backend\requirements.txt --quiet
   cd ecommerce\frontend\smartwms-angular && npm install && cd ..\..
   ```
4. **Verificar estado de base de datos:**
   ```bash
   python scripts\init_db.py
   ```
5. **Iniciar el sistema:**
   ```bash
   iniciar.bat
   ```

---

## 10. Resumen de Puertos Utilizados

| Puerto | Protocolo | Servicio | Descripción |
| :---: | :---: | :--- | :--- |
| **8001** | HTTP / WS | Backend API (FastAPI) | Endpoints REST, autenticación JWT y WebSockets de pedidos |
| **8000** | HTTP | Bot IA y Chatbot | Servicio de inteligencia artificial y copiloto |
| **4200** | HTTP | Frontend Web (Angular) | Portal web para supervisores y operarios |
