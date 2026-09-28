import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const { SIH_PORT = "8000" } = loadEnv(mode, "../", "SIH_");

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": `http://127.0.0.1:${SIH_PORT}`,
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
      restoreMocks: true,
    },
  };
});
