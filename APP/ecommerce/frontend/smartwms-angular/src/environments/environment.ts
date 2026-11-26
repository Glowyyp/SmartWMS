// environments/environment.ts — Detección automática del host del servidor
// Permite que la app web funcione en localhost o desde cualquier otra IP en la red local/VPN
const getHost = (): string => {
  if (typeof window !== 'undefined' && window.location && window.location.hostname) {
    return window.location.hostname;
  }
  return '127.0.0.1';
};

export const environment = {
  production: false,
  apiUrl: `http://${getHost()}:8001`,
  botApiUrl: `http://${getHost()}:8000`,
};
