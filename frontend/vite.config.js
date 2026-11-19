import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const target = process.env.VITE_PROXY_TARGET || 'http://backend:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/health': { target, changeOrigin: true },
    },
  },
});
