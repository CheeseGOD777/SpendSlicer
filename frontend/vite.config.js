import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendUrl = process.env.VITE_BACKEND_URL || "http://127.0.0.1:8080";

export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backendUrl,
    },
  },
  build: {
    // Build straight into the Python package so one path serves the bundle in
    // a source checkout, an installed wheel, and a frozen desktop build.
    outDir: "../costsight/web/static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          recharts: ["recharts"],
          react: ["react", "react-dom"],
        },
      },
    },
  },
});
