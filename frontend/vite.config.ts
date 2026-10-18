import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const CLOUD_RUN_API =
  process.env.REVIVEAI_DEV_PROXY_TARGET ||
  "https://reviveai-api-knusxffuaq-as.a.run.app";

function rewriteSetCookieForLocalhost(value: string): string {
  return value
    .replace(/;\s*Secure/gi, "")
    .replace(/;\s*SameSite=None/gi, "; SameSite=Lax")
    .replace(/;\s*Domain=[^;]+/gi, "");
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: CLOUD_RUN_API,
        changeOrigin: true,
        secure: true,
        configure(proxy) {
          proxy.on("proxyRes", (proxyRes) => {
            const setCookie = proxyRes.headers["set-cookie"];
            if (Array.isArray(setCookie)) {
              proxyRes.headers["set-cookie"] =
                setCookie.map(rewriteSetCookieForLocalhost);
            } else if (typeof setCookie === "string") {
              proxyRes.headers["set-cookie"] =
                rewriteSetCookieForLocalhost(setCookie);
            }
          });
          proxy.on("error", (error, req) => {
            console.error(
              `[ReviveAI Vite proxy] ${req.method} ${req.url} failed:`,
              error,
            );
          });
        },
      },
    },
  },
});
