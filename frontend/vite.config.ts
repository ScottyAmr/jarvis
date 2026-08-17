import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/ws": {
        target: "https://127.0.0.1:8340",
        ws: true,
        secure: false,
      },
      "/api": {
        target: "https://127.0.0.1:8340",
        secure: false,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
