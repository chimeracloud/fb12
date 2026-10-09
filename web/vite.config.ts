import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser never sees FB12's Cloud Run URL: every /api and /admin call goes to the
// Pages Function on this same hostname (web/functions), which forwards it with the
// Cloudflare Access token. Nothing here reaches the API directly.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
});
