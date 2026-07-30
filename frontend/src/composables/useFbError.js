// FB 错误 category → i18n key registry（投放/保活失败原因翻译）。仿 useStatus。
// 新增错误类型：这里加 category→key + locale 的 fbError 命名空间加译文。
import i18n from '../i18n'
const t = i18n.global.t

const FB_ERRORS = {
  cert_required: 'fbError.cert_required',
  invalid_param: 'fbError.invalid_param',
  bid_required: 'fbError.bid_required',
  regulated_opt: 'fbError.regulated_opt',
  regulated_missing: 'fbError.regulated_missing',
  audience: 'fbError.audience',
  audience_size: 'fbError.audience_size',
  abuse: 'fbError.abuse',
  dev_mode: 'fbError.dev_mode',
  rate_limited: 'fbError.rate_limited',
  has_spend: 'fbError.has_spend',
  no_write_token: 'fbError.no_write_token',
  has_keepalive: 'fbError.has_keepalive',
  no_page: 'fbError.no_page',
  no_page_token: 'fbError.no_page_token',
  no_asset: 'fbError.no_asset',
  asset_missing: 'fbError.asset_missing',
  error: 'fbError.error',
}

// category → 翻译后的人话原因；未知 category 兜底 generic；空 category 返回空
export const fbErrorText = (category) => {
  if (!category) return ''
  return t(FB_ERRORS[category] || 'fbError.generic')
}
