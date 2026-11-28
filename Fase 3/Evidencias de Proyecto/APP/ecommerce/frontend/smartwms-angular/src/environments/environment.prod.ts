// environments/environment.prod.ts — Configuración de producción para Google Cloud Platform
// El backend en Cloud Run expone tanto la API REST como el proxy /api/chat hacia el Bot IA.
export const environment = {
  production: true,
  apiUrl: 'https://smartwms-backend-523602689123.southamerica-west1.run.app',
  botApiUrl: 'https://smartwms-backend-523602689123.southamerica-west1.run.app',
};
