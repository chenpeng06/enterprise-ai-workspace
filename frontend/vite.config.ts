import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";

const GATEWAY_PROXY_TARGET = "http://127.0.0.1:8080";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const gatewayTarget = env.VITE_GATEWAY_PROXY_TARGET || GATEWAY_PROXY_TARGET;

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      watch: {
        ignored: ["**/*.tmpdir/**", "**/*.tmp", "**/.*.tmpdir/**"],
      },
      proxy: {
        "/api": { target: gatewayTarget, changeOrigin: true },
        "/healthz": { target: gatewayTarget, changeOrigin: true },
        "/readyz": { target: gatewayTarget, changeOrigin: true },
      },
    },
    preview: {
      host: "127.0.0.1",
      port: 4173,
    },
    build: {
      outDir: "dist",
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ["react", "react-dom", "react-router-dom"],
            query: ["@tanstack/react-query"],
          },
        },
      },
    },
  };
});
