import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Puerto fijo: lo espera tauri.conf.json en `devUrl`.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"], css: false },
});
