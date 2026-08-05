import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/transcribe': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/transcribe_stream': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/confirm': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/pending': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/history': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/session': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/speak': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/permissions': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/view_document': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
});

