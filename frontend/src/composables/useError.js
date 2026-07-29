// 智能错误展示：长错误 / FB·API 错误 → 持久弹窗 + 复制按钮（不自动消失）；短错误 → toast。
// 用法：catch (e) { showError(e) } 或 showError(e, '部署失败')
import { ElMessage, ElMessageBox } from 'element-plus'
import i18n from '../i18n'
const t = i18n.global.t

const _escapeHtml = (s) => String(s).replace(/[&<>"']/g, c => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
))
const _copy = (text) => {
  try {
    navigator.clipboard?.writeText(text)
    ElMessage.success(t('error.copiedError'))
  } catch {
    ElMessage.warning(t('error.copyFail'))
  }
}

// 判断是否需要"重"展示（持久弹窗）
const _isHeavy = (msg) => {
  if (!msg) return false
  if (msg.length > 90) return true
  // FB / 网络类错误通常需要看清全文 + 可能要贴给开发
  return /Meta App|Facebook|FB API|开发者模式|限流|权限|permission|invalid|error|失败|超时|timeout|500|502|503|504/i.test(msg)
}

export function showError(e, title) {
  const msg = typeof e === 'string' ? e : (e?.message || String(e || ''))
  if (!msg) return
  if (_isHeavy(msg)) {
    ElMessageBox.alert(
      `<div style="max-height:50vh;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.6;color:var(--t1, #1d1d1f)">${_escapeHtml(msg)}</div>`,
      title || t('error.opFail'),
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: t('error.copyBtn'),
        cancelButtonText: t('common.close'),
        showCancelButton: true,
        distinguishCancelAndClose: true,
        type: 'error',
        closeOnClickModal: false,
      }
    ).then(() => _copy(msg)).catch((action) => { if (action === 'cancel') return })  // 关闭按钮 / 点外面都不复制
  } else {
    ElMessage.error(msg)
  }
}

// 全局兜底：未被 try/catch 接住的 Promise 异常 / 同步错误，确保一定显示出来
export function installGlobalErrorHandler() {
  window.addEventListener('unhandledrejection', (ev) => {
    const e = ev?.reason
    const msg = e?.message || String(e || t('error.unknown'))
    showError(msg, t('error.uncaptured'))
    // 不阻止控制台报错
  })
  window.addEventListener('error', (ev) => {
    // 资源加载错误 (target=img/link/script) 不弹，太吵
    if (ev?.target && ev.target !== window) return
    if (ev?.message) showError(ev.message, t('error.pageError'))
  }, true)
}
