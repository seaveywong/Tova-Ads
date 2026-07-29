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
  function setLocale(l) { if (EP[l]) apply(l) }
  function toggle() { apply(locale.value === 'zh' ? 'en' : 'zh') }
  return { locale, epLocale, setLocale, toggle }
}
