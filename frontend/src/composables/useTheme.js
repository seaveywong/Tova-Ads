import { ref } from 'vue'

const theme = ref(localStorage.getItem('tova_theme') || 'dark')

// 初始化：应用主题到 <html>
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t)
}
applyTheme(theme.value)

export function useTheme() {
  function toggle() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    applyTheme(theme.value)
    localStorage.setItem('tova_theme', theme.value)
  }
  return { theme, toggle }
}
