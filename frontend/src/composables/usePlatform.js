// 平台切换器全局状态（纯前端：localStorage 持久，不发后端请求、不换 token、不影响团队上下文）。
// MainLayout topbar 写，各页读：'all'（默认，跨平台汇总）| 'fb' | 'tt'。
// 模块级单例 ref——同会话所有组件共享，切一处全站生效。
import { ref } from 'vue'

const STORAGE_KEY = 'tova_platform'

const _read = () => {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return v === 'fb' || v === 'tt' ? v : 'all'
  } catch { return 'all' }
}
const platform = ref(_read())

export function usePlatform() {
  const setPlatform = (v) => {
    platform.value = (v === 'fb' || v === 'tt') ? v : 'all'
    try { localStorage.setItem(STORAGE_KEY, platform.value) } catch {}
  }
  return { platform, setPlatform }
}

// 便捷拼参：?platform= 只在 fb/tt 时附加——all 不带参，请求与旧版逐字节一致
export const platformQuery = () => (platform.value !== 'all' ? `&platform=${platform.value}` : '')
