// 语言切换 composable（仿 useTheme）。locale 切换实时生效、写入 localStorage、
// 并驱动 Element Plus 的 locale（经 App.vue 的 el-config-provider）。
import { computed, ref } from 'vue'
import i18n from '../i18n'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import enEp from 'element-plus/es/locale/lang/en'

const STORAGE_KEY = 'tova_locale'
const EP = { zh: zhCn, en: enEp }

// 把 i18n 的 locale 镜像进 ref，模板里可响应式消费
const locale = ref(i18n.global.locale.value)

function apply(l) {
  i18n.global.locale.value = l
  locale.value = l
  localStorage.setItem(STORAGE_KEY, l)
  document.documentElement.setAttribute('lang', l === 'zh' ? 'zh-CN' : 'en')
}
// 初始化 <html lang>
document.documentElement.setAttribute('lang', locale.value === 'zh' ? 'zh-CN' : 'en')

export function useLocale() {
  const epLocale = computed(() => EP[locale.value] || EP.zh)
  function setLocale(l) {
    if (!EP[l]) return
    apply(l)
    // 持久化到后端用户档案（登录态才发；通知按租户 owner 的 locale 渲染）
    try {
      if (localStorage.getItem('tova_token')) {
        import('../api').then(({ PATCH }) => PATCH('/auth/me', { locale: l }).catch(() => {}))
      }
    } catch {}
  }
  function toggle() { setLocale(locale.value === 'zh' ? 'en' : 'zh') }
  return { locale, epLocale, setLocale, toggle }
}
