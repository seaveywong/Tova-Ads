import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需引入（批3 bundle 减重）：模板里的 el-* 组件按用到的自动 import + 注入对应样式，
    // 不再全量 app.use(ElementPlus)。指令式 API（ElMessage 等）的样式在 main.js 手动补
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
  build: {
    // 源码本就推 GitHub（非机密），开 sourcemap 让生产报错能直接定位行号
    // （之前 LaunchTemplates 的 Vue 报错全是 minified，无法定位）
    sourcemap: true,
  },
})
