import tailwindcss from "@tailwindcss/vite";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    proxy: {
      // 配置 API 代理到后端（避免 fetch 打到 Vite 返回 index.html）
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
