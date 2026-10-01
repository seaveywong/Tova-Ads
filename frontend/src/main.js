import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElLoading } from 'element-plus'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './styles/main.css'
import { installGlobalErrorHandler, showError } from './composables/useError'
// Element Plus 按需引入（批3）：el-* 组件与样式由 unplugin-vue-components 按模板实际用到的注入（见 vite.config.js）。
// 指令式 API 不走模板解析器，样式在此手动补齐；v-loading 指令全站使用，须注册 ElLoading
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/loading/style/css'
import 'element-plus/es/components/notification/style/css'
import 'element-plus/theme-chalk/dark/css-vars.css'

installGlobalErrorHandler()  // 兜底：未捕获的 Promise/同步错误一定回显

// 抑制 ResizeObserver loop 良性警告（Chrome/Edge 已知行为，非 bug——EP 表格/抽屉
// resize 回调连锁触发浏览器自动截断；不影响功能，只是控制台碍眼）
// 双保险：① error 事件捕获阶段拦截 ② console.error 过滤（Chrome 有时不走 error event）
window.addEventListener('error', (e) => {
  if (e.message?.includes('ResizeObserver loop')) {
    e.preventDefault()
    e.stopImmediatePropagation()
  }
}, true)
const _consoleError = console.error
console.error = (...args) => {
  if (args.length > 0 && String(args[0]).includes('ResizeObserver loop')) return
  _consoleError(...args)
}

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElLoading)   // 注册 v-loading 指令 + $loading 服务（原 app.use(ElementPlus) 承担，按需化后单独注册）
// Vue 组件渲染/生命周期错误默认只进 console（不触发 window error），这里捕获并弹窗回显，
// 便于定位（如"点广告组 Tab 弹窗消失"这类渲染崩溃）。配合 sourcemap，console 里能看到源码行。
app.config.errorHandler = (err, instance, info) => {
  console.error('[Vue error]', info, err)
  const where = instance?.$?.type?.__name || instance?.$options?.name || ''
  showError(`${err?.message || String(err)} [${info}${where ? ' @ ' + where : ''}]`, 'Vue 渲染错误')
}
app.mount('#app')
