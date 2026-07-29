// 中央日期范围预设 + 北京业务日格式化。
// 基准统一为北京业务日（Asia/Shanghai），对齐后端 snapshot 的账户本地日 ——
// 之前 Dashboard/Ads/AdManager 用 new Date().toISOString()(UTC)，跨午夜会差一天。
// （见 toveads-date-dual-basis：看数据 = 北京业务日）
// label 用 getter 包 t()，locale 切换实时生效，调用方仍用 p.label。
import i18n from '../i18n'
const t = i18n.global.t

const TZ = 'Asia/Shanghai'

// 任意 Date → 北京日字符串 YYYY-MM-DD
export function bjDateStr(d) {
  const dt = d instanceof Date ? d : new Date(d)
  if (isNaN(dt)) return ''
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(dt)
}
// 今天往前后偏 n 天的北京日（n<0 = 过去）
function bjOffset(n) {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return bjDateStr(d)
}
// 今天（北京）
export const todayStr = () => bjOffset(0)

// 统一预设列表：返回 [from, to]（北京日字符串）
// key=语义id（presetRange 匹配用）；tkey=i18n key；label=getter 实时翻译
export const DATE_PRESETS = [
  { key: 'today',     tkey: 'common.today',     get label() { return t(this.tkey) }, range: () => [bjOffset(0),  bjOffset(0)]  },
  { key: 'yesterday', tkey: 'common.yesterday', get label() { return t(this.tkey) }, range: () => [bjOffset(-1), bjOffset(-1)] },
  { key: 'last_2d',   tkey: 'common.last2days', get label() { return t(this.tkey) }, range: () => [bjOffset(-1), bjOffset(0)]  },
  { key: 'last_7d',   tkey: 'common.last7days', get label() { return t(this.tkey) }, range: () => [bjOffset(-6), bjOffset(0)]  },
  { key: 'last_30d',  tkey: 'common.last30days', get label() { return t(this.tkey) }, range: () => [bjOffset(-29), bjOffset(0)] },
]
// 按 key 取 [from, to]，未知 key 返回 null
export function presetRange(key) {
  const p = DATE_PRESETS.find(x => x.key === key)
  return p ? p.range() : null
}
// el-date-picker 的 shortcuts（供 AuditLog 等日历选择器用）
export function dateShortcuts() {
  return DATE_PRESETS.map(p => ({
    text: t(p.tkey),
    value: () => {
      const [f, t2] = p.range()
      // 构造北京 00:00 的 Date，让 picker 选中对应日
      return [new Date(f + 'T00:00:00+08:00'), new Date(t2 + 'T23:59:59+08:00')]
    },
  }))
}
