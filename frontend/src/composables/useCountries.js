// 国家码中央 registry（受众定向/资产分析/屏蔽分布共用一份表）。
// 统一结构 { code: { en, zh } }，按当前 locale 取名。
// label 用 getter 包实现 locale 切换实时生效（对齐 useDateRange 的模式）。
import i18n from '../i18n'

const NAMES = {
  US: { en: 'United States', zh: '美国' }, VN: { en: 'Vietnam', zh: '越南' }, TH: { en: 'Thailand', zh: '泰国' },
  ID: { en: 'Indonesia', zh: '印度尼西亚' }, PH: { en: 'Philippines', zh: '菲律宾' }, MY: { en: 'Malaysia', zh: '马来西亚' },
  TW: { en: 'Taiwan', zh: '台湾' }, HK: { en: 'Hong Kong', zh: '香港' }, SG: { en: 'Singapore', zh: '新加坡' },
  CN: { en: 'Mainland China', zh: '中国大陆' }, BR: { en: 'Brazil', zh: '巴西' }, MX: { en: 'Mexico', zh: '墨西哥' },
  IN: { en: 'India', zh: '印度' }, JP: { en: 'Japan', zh: '日本' }, KR: { en: 'South Korea', zh: '韩国' },
  GB: { en: 'United Kingdom', zh: '英国' }, DE: { en: 'Germany', zh: '德国' }, FR: { en: 'France', zh: '法国' },
  AE: { en: 'UAE', zh: '阿联酋' }, SA: { en: 'Saudi Arabia', zh: '沙特阿拉伯' }, EG: { en: 'Egypt', zh: '埃及' },
  KW: { en: 'Kuwait', zh: '科威特' }, QA: { en: 'Qatar', zh: '卡塔尔' }, TR: { en: 'Turkey', zh: '土耳其' },
  ES: { en: 'Spain', zh: '西班牙' }, IT: { en: 'Italy', zh: '意大利' }, CA: { en: 'Canada', zh: '加拿大' },
  AU: { en: 'Australia', zh: '澳大利亚' }, NZ: { en: 'New Zealand', zh: '新西兰' }, CL: { en: 'Chile', zh: '智利' },
  CO: { en: 'Colombia', zh: '哥伦比亚' }, PE: { en: 'Peru', zh: '秘鲁' }, AR: { en: 'Argentina', zh: '阿根廷' },
  ZA: { en: 'South Africa', zh: '南非' }, NG: { en: 'Nigeria', zh: '尼日利亚' }, KE: { en: 'Kenya', zh: '肯尼亚' },
  BD: { en: 'Bangladesh', zh: '孟加拉国' }, PK: { en: 'Pakistan', zh: '巴基斯坦' }, PL: { en: 'Poland', zh: '波兰' },
  NL: { en: 'Netherlands', zh: '荷兰' }, BE: { en: 'Belgium', zh: '比利时' }, CH: { en: 'Switzerland', zh: '瑞士' },
  AT: { en: 'Austria', zh: '奥地利' }, SE: { en: 'Sweden', zh: '瑞典' }, NO: { en: 'Norway', zh: '挪威' },
  DK: { en: 'Denmark', zh: '丹麦' }, FI: { en: 'Finland', zh: '芬兰' }, PT: { en: 'Portugal', zh: '葡萄牙' },
  GR: { en: 'Greece', zh: '希腊' }, CZ: { en: 'Czechia', zh: '捷克' }, RO: { en: 'Romania', zh: '罗马尼亚' },
  HU: { en: 'Hungary', zh: '匈牙利' }, IL: { en: 'Israel', zh: '以色列' }, IE: { en: 'Ireland', zh: '爱尔兰' },
  RU: { en: 'Russia', zh: '俄罗斯' }, UA: { en: 'Ukraine', zh: '乌克兰' }, BY: { en: 'Belarus', zh: '白俄罗斯' },
  KZ: { en: 'Kazakhstan', zh: '哈萨克斯坦' }, UZ: { en: 'Uzbekistan', zh: '乌兹别克斯坦' },
  GH: { en: 'Ghana', zh: '加纳' }, TZ: { en: 'Tanzania', zh: '坦桑尼亚' }, UG: { en: 'Uganda', zh: '乌干达' },
  ET: { en: 'Ethiopia', zh: '埃塞俄比亚' }, MA: { en: 'Morocco', zh: '摩洛哥' }, DZ: { en: 'Algeria', zh: '阿尔及利亚' },
  TN: { en: 'Tunisia', zh: '突尼斯' }, IQ: { en: 'Iraq', zh: '伊拉克' }, JO: { en: 'Jordan', zh: '约旦' },
  LB: { en: 'Lebanon', zh: '黎巴嫩' }, BH: { en: 'Bahrain', zh: '巴林' }, OM: { en: 'Oman', zh: '阿曼' },
  PS: { en: 'Palestine', zh: '巴勒斯坦' }, LK: { en: 'Sri Lanka', zh: '斯里兰卡' }, NP: { en: 'Nepal', zh: '尼泊尔' },
  MM: { en: 'Myanmar', zh: '缅甸' }, KH: { en: 'Cambodia', zh: '柬埔寨' }, LA: { en: 'Laos', zh: '老挝' },
  BN: { en: 'Brunei', zh: '文莱' }, MO: { en: 'Macao', zh: '澳门' }, PY: { en: 'Paraguay', zh: '巴拉圭' },
  UY: { en: 'Uruguay', zh: '乌拉圭' }, BO: { en: 'Bolivia', zh: '玻利维亚' }, VE: { en: 'Venezuela', zh: '委内瑞拉' },
  EC: { en: 'Ecuador', zh: '厄瓜多尔' }, PA: { en: 'Panama', zh: '巴拿马' }, GT: { en: 'Guatemala', zh: '危地马拉' },
  DO: { en: 'Dominican Republic', zh: '多米尼加' }, CR: { en: 'Costa Rica', zh: '哥斯达黎加' }, SV: { en: 'El Salvador', zh: '萨尔瓦多' },
  HN: { en: 'Honduras', zh: '洪都拉斯' }, JM: { en: 'Jamaica', zh: '牙买加' }, TT: { en: 'Trinidad and Tobago', zh: '特立尼达和多巴哥' },
  PR: { en: 'Puerto Rico', zh: '波多黎各' }, IS: { en: 'Iceland', zh: '冰岛' }, LU: { en: 'Luxembourg', zh: '卢森堡' },
  MT: { en: 'Malta', zh: '马耳他' }, CY: { en: 'Cyprus', zh: '塞浦路斯' }, HR: { en: 'Croatia', zh: '克罗地亚' },
  SK: { en: 'Slovakia', zh: '斯洛伐克' }, SI: { en: 'Slovenia', zh: '斯洛文尼亚' }, BG: { en: 'Bulgaria', zh: '保加利亚' },
  RS: { en: 'Serbia', zh: '塞尔维亚' }, LT: { en: 'Lithuania', zh: '立陶宛' }, LV: { en: 'Latvia', zh: '拉脱维亚' },
  EE: { en: 'Estonia', zh: '爱沙尼亚' }, AL: { en: 'Albania', zh: '阿尔巴尼亚' }, BA: { en: 'Bosnia and Herzegovina', zh: '波黑' },
  MD: { en: 'Moldova', zh: '摩尔多瓦' },
}

const localeOf = () => (i18n.global.locale.value === 'en' ? 'en' : 'zh')

export function countryName(code) {
  const n = NAMES[String(code || '').toUpperCase()]
  return n ? n[localeOf()] : ''
}

// 下拉选项列表（LaunchTemplates 受众定向全量 / Assets 资产分析取子集均可）
export const COUNTRIES = Object.keys(NAMES).map(code => ({
  code,
  get label() { return countryName(code) },
}))

// 屏蔽分布等展示用：国名 + 码（"United States US"）；未知码原样返回
export function countryLabel(code) {
  const c = String(code || '').toUpperCase()
  if (!c) return '-'
  const name = countryName(c)
  return name ? `${name} ${c}` : c
}
