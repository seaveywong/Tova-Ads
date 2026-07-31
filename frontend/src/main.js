import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './styles/main.css'
import { installGlobalErrorHandler, showError } from './composables/useError'

installGlobalErrorHandler()  // 兜底：未捕获的 Promise/同步错误一定回显

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus)
// Vue 组件渲染/生命周期错误默认只进 console（不触发 window error），这里捕获并弹窗回显，
// 便于定位（如"点广告组 Tab 弹窗消失"这类渲染崩溃）。配合 sourcemap，console 里能看到源码行。
app.config.errorHandler = (err, instance, info) => {
  console.error('[Vue error]', info, err)
  const where = instance?.$?.type?.__name || instance?.$options?.name || ''
  showError(`${err?.message || String(err)} [${info}${where ? ' @ ' + where : ''}]`, 'Vue 渲染错误')
}
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}
app.mount('#app')
