import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The React app calls /api/... and Vite forwards those requests to FastAPI.
// Change BACKEND_URL if your backend runs on another port.
const BACKEND_URL = process.env.BACKEND_URL || "http://127.0.0.1:5001";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: BACKEND_URL, changeOrigin: true } },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    proxy: { "/api": { target: BACKEND_URL, changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: false },
});
