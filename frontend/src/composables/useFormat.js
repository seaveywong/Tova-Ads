// 金额/数字格式化中央 registry。
// 语义约定：null/undefined → '—'（无数据）；0 → 按真值格式化（真零 ≠ 无数据）。
export function fmtUsd(v, digits = 2) {
  if (v == null) return '—'
  return '$' + Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtNum(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString()
}
