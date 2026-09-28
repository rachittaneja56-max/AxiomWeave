import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const { SIH_PORT = "8000", SIH_GOOGLE_CLIENT_ID = "" } = loadEnv(
    mode,
    "../",
    "SIH_",
  );

  return {
    plugins: [react()],
    define: {
      "import.meta.env.VITE_GOOGLE_CLIENT_ID":
        JSON.stringify(SIH_GOOGLE_CLIENT_ID),
    },
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
