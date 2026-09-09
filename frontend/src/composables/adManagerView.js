// Shared entity identity and list behavior for the three Ads Manager levels.
export const entityId = value => String(value && typeof value === 'object' ? value.id ?? '' : value ?? '')
export const entityKey = row => `${row.platform || 'fb'}:${row.act_id}:${entityId(row.id)}`
const parentKey = (row, id) => `${row.platform || 'fb'}:${row.act_id}:${entityId(id)}`

export const METRIC_COLUMNS = [
  { id: 'objective', label: 'colObjective', levels: ['campaign'], width: 140 },
  { id: 'optimization_goal', label: 'colOptGoal', levels: ['adset'], width: 160 },
  { id: 'pixel', label: 'colPixel', levels: ['adset'], width: 150 },
  // 顺序照 FB Ads Manager 默认列：成效 → 消耗 → 单次成效费用 → 预算 → …（批H）
  { id: 'results_fb', label: 'resultsFb', width: 120, sort: 'results_fb' },
  { id: 'spend', label: 'colSpend', width: 120, sort: 'spend' },
  { id: 'cost_per_result', label: 'costPerResult', width: 140, sort: 'cost_per_result' },
  { id: 'budget', label: 'colBudget', levels: ['campaign', 'adset'], width: 190, sort: 'daily_budget_amount' },
  { id: 'conversions', label: 'totalConversions', width: 125, sort: 'conversions' },
  { id: 'cpa', label: 'combinedCpa', width: 140, sort: 'cpa' },
  { id: 'impressions', label: 'diagImpressions', width: 115, sort: 'impressions' },
  { id: 'reach', label: 'colReach', width: 110, sort: 'reach' },
  { id: 'frequency', label: 'colFrequency', width: 100, sort: 'frequency' },
  { id: 'clicks', label: 'diagClicks', width: 100, sort: 'clicks' },
  { id: 'ctr', label: 'ctrLabel', width: 100, sort: 'ctr' },
  { id: 'slug', label: 'colSubcode', levels: ['ad'], width: 140 },
  { id: 'landing_visits', label: 'colVisits', levels: ['ad'], width: 115, sort: 'landing_visits' },
  { id: 'landing_pass', label: 'colPass', levels: ['ad'], width: 115, sort: 'landing_pass' },
  { id: 'pass_rate', label: 'colPassRate', levels: ['ad'], width: 110 },
]
export const columnsFor = level => METRIC_COLUMNS.filter(c => !c.levels || c.levels.includes(level))
// 批AO 修复：批AM 提交时此行少了收尾 ]，前端从批AM 起就 build 失败（改动从未上 CF）
export const defaultColumns = level => ['results_fb', 'spend', 'cost_per_result', 'budget', 'conversions', ...(level === 'adset' ? ['pixel'] : []), ...(level === 'ad' ? ['ctr', 'landing_pass'] : []).filter(id => columnsFor(level).some(c => c.id === id))]

export function entityContext(data) {
  const campaigns = new Map((data.campaigns || []).map(row => [entityKey(row), row]))
  const adsets = new Map((data.adsets || []).map(row => [entityKey(row), row]))
  return row => {
    const adset = adsets.get(parentKey(row, row.adset_id))
    const campaign = campaigns.get(parentKey(row, row.campaign_id || adset?.campaign_id))
    return { campaign, adset }
  }
}

export function searchMatches(row, query, context) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (!terms.length) return true
  const { campaign, adset } = context(row)
  const values = [row.name, row.id, row.account_name, row.act_id, campaign?.name, campaign?.id, adset?.name, adset?.id]
  const haystack = values.map(v => entityId(v).toLocaleLowerCase()).join(' ')
  return terms.every(term => haystack.includes(term))
}

export const fbResult = row => row.results_fb_complete === false || row.results_fb == null || row.results_fb_available === false ? null : Number(row.results_fb)

export function compareRows(a, b, { key, direction, mixedCurrency, blocked, statusRank }) {
  const availability = Number(blocked(a)) - Number(blocked(b))
  if (availability) return availability
  if (key === '_status_rank') {
    const diff = statusRank(a.effective_status) - statusRank(b.effective_status)
    return direction === 'desc' ? diff : -diff
  }
  let field = key
  if (mixedCurrency && ['spend', 'cpa', 'cost_per_result'].includes(field)) field += '_usd'
  if (key === 'daily_budget_amount' && a.currency !== b.currency) return String(a.currency).localeCompare(String(b.currency))
  const value = row => key === 'results_fb' ? fbResult(row) : key === 'daily_budget_amount'
    ? row.daily_budget_amount ?? row.lifetime_budget_amount ?? null : row[field] ?? null
  const va = value(a), vb = value(b)
  if (va == null || vb == null) return va == null ? (vb == null ? entityKey(a).localeCompare(entityKey(b)) : 1) : -1
  const diff = key === 'name' ? String(va).localeCompare(String(vb), undefined, { numeric: true }) : Number(va) - Number(vb)
  if (diff) return direction === 'asc' ? diff : -diff
  return statusRank(a.effective_status) - statusRank(b.effective_status) || entityKey(a).localeCompare(entityKey(b))
}

export function normalizeViewPreferences(raw) {
  const out = {}
  for (const level of ['campaign', 'adset', 'ad']) {
    const saved = raw?.[level] || {}
    const allowed = new Set(columnsFor(level).map(c => c.id))
    const sortKeys = new Set(['name', '_status_rank', ...columnsFor(level).map(c => c.sort).filter(Boolean)])
    out[level] = {
      columns: Array.isArray(saved.columns) ? [...new Set(saved.columns.filter(id => allowed.has(id)))] : defaultColumns(level),
      sortKey: sortKeys.has(saved.sortKey) ? saved.sortKey : 'spend',
      sortDir: saved.sortDir === 'asc' ? 'asc' : 'desc',
    }
  }
  return out
}
