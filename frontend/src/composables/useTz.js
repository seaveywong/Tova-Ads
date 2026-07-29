import { ref } from 'vue'
import i18n from '../i18n'

// 用户显示时区（仅前端展示，不影响广告账户本地时区）。
// 登录后从 /auth/me 取 timezone 填入；设置页改时区时更新。
let _storedTz = 'Asia/Shanghai'
try { _storedTz = localStorage.getItem('tova_tz') || 'Asia/Shanghai' } catch {}
export const userTz = ref(_storedTz)

export const setUserTz = (tz) => {
  if (!tz) return
  userTz.value = tz
  localStorage.setItem('tova_tz', tz)
}

// UTC 时间字符串 → 用户时区显示（止损明细/告警/通知统一用）。
// 兼容 ISO+偏移 / Z / 裸 "YYYY-MM-DD HH:MM:SS"(当 UTC)。
// 显示语言跟随当前 locale（中文 zh-CN / 英文 en-US）。
export const fmtTime = (s) => {
  if (!s || s === 'None') return '—'
  let d = new Date(s)
  if (isNaN(d) && typeof s === 'string') {
    const hasTz = s.endsWith('Z') || /[+-]\d\d:?\d\d$/.test(s)
    d = new Date(s.replace(' ', 'T') + (hasTz ? '' : 'Z'))
  }
  if (isNaN(d)) return String(s)
  const fmtLocale = i18n.global.locale.value === 'en' ? 'en-US' : 'zh-CN'
  return d.toLocaleString(fmtLocale, { timeZone: userTz.value, hour12: false }).replace(/\//g, '-')
}
