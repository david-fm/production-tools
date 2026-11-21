import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const mock = (name: string) => fileURLToPath(new URL(`./mocks/${name}.ts`, import.meta.url));

// Misma app, pero con la capa de Tauri sustituida por un puente al motor real (ver e2e/run.mjs).
export default defineConfig({
  root: fileURLToPath(new URL("..", import.meta.url)),
  plugins: [react()],
  resolve: {
    alias: {
      "@tauri-apps/api/core": mock("core"),
      "@tauri-apps/api/event": mock("event"),
      "@tauri-apps/api/webview": mock("webview"),
      "@tauri-apps/api/path": mock("path"),
      "@tauri-apps/plugin-dialog": mock("dialog"),
    },
  },
  server: { port: 1421, strictPort: true },
});
