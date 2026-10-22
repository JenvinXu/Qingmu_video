import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  root: 'apps/workbench', base: './', plugins: [react()],
  build: { outDir: '../../dist/workbench', emptyOutDir: true },
  server: { host: '127.0.0.1', port: 5178, strictPort: true }
});
