/** Vite development and test configuration for the React client. */
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/** Keep local API traffic on FastAPI and test pure UI helpers with Vitest. */
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { environment: "node" },
});
