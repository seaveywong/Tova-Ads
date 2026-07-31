import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    // 源码本就推 GitHub（非机密），开 sourcemap 让生产报错能直接定位行号
    // （之前 LaunchTemplates 的 Vue 报错全是 minified，无法定位）
    sourcemap: true,
  },
})
