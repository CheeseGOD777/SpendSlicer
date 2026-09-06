import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// The landing site is a separate Vite project on purpose. The dashboard's
// config builds into ../spendslicer/web/static with emptyOutDir, and
// pyproject.toml ships that whole directory inside the wheel. A marketing
// page must not ride along in `pip install spendslicer`.
export default defineConfig({
  // Relative base, so the build works at a domain root or a Pages subpath.
  base: "./",
  plugins: [react()],
  resolve: {
    alias: {
      // One source of truth for the design system: the product's own files.
      "@app": fileURLToPath(new URL("../frontend/src", import.meta.url)),
    },
  },
  server: {
    port: 5174,
    // Dev server needs to read ../frontend/src for the shared design system.
    fs: { allow: [".."] },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // Recharts is deliberately not named here: it is reached only through
        // the lazily loaded Surfaces section, so Rollup should keep it there
        // rather than hoisting it into the first paint.
        manualChunks: { react: ["react", "react-dom"] },
      },
    },
  },
});
