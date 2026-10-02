import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base './' — the panel is served from a secret path chosen at install time
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        // charts and the React runtime change rarely: separate files stay cached between updates
        manualChunks: { charts: ['recharts'], icons: ['lucide-react'] },
      },
    },
  },
  server: {
    proxy: { '/panel/api': { target: 'http://127.0.0.1:8000', ws: true } },
  },
})
