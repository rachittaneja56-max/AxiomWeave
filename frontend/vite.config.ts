import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";

type RuntimeEnvironment = Record<string, string | undefined>;

function runtimeEnvironment(): RuntimeEnvironment {
  const runtime = globalThis as typeof globalThis & {
    process?: { env?: RuntimeEnvironment };
  };
  return runtime.process?.env ?? {};
}

export default defineConfig(({ mode }) => {
  const fileEnv = loadEnv(mode, "../", "SIH_");
  const runtimeEnv = runtimeEnvironment();

  const port = runtimeEnv.SIH_PORT ?? fileEnv.SIH_PORT ?? "8000";
  const googleClientId =
    runtimeEnv.SIH_GOOGLE_CLIENT_ID ?? fileEnv.SIH_GOOGLE_CLIENT_ID ?? "";
  const apiProxyTarget =
    runtimeEnv.SIH_API_PROXY_TARGET ??
    fileEnv.SIH_API_PROXY_TARGET ??
    `http://127.0.0.1:${port}`;

  const proxy = {
    "/api": apiProxyTarget,
  };

  return {
    plugins: [react()],
    define: {
      "import.meta.env.VITE_GOOGLE_CLIENT_ID": JSON.stringify(googleClientId),
    },
    server: {
      proxy,
    },
    preview: {
      proxy,
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test-setup.ts"],
      restoreMocks: true,
    },
  };
});
