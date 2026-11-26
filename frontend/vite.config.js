import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// VITE_BASE lets GitHub Pages serve from /<repo>/
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE || '/',
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
