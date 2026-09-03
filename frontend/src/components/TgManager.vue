<script setup>
// TG 绑定管理中心：我的绑定(列表+解绑+测试) / 添加绑定(深链+命令+widget+手动) / 团队成员清单(owner)
// 用法：<TgManager ref="tg" /> + tg.value.open()（仪表盘/设置页通用）
import { ref, computed, nextTick, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { GET, POST, DELETE } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

defineOptions({ inheritAttrs: false })
const { t } = useI18n()

const dlgOpen = ref(false)
const tab = ref('mine')
const loading = ref(true)
const botInfo = ref({})
const userB = ref({ bound: false, bindings: [] })
const bindLink = ref('')
const bindCommand = ref('')
const waiting = ref(false)
const manual = ref({ chat_id: '', saving: false })
const team = ref({ loading: false, members: [] })
const canManage = ref(false)

const bindings = computed(() => userB.value.bindings || [])

const fmtTs = (iso) => {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

const load = async () => {
  loading.value = true
  try {
    const [bi, ub] = await Promise.all([
      GET('/notifications/tg/bot-info'),
      GET('/notifications/tg/user-binding'),
    ])
    botInfo.value = bi
    userB.value = ub
    if (!ub.bound) tab.value = 'add'
    try { canManage.value = ((await GET('/auth/me')).permissions || []).includes('members.manage') } catch {}
    await refreshCode()
  } catch (e) { ElMessage.error(e.message || t('tg.loadFail')) }
  loading.value = false
}

const refreshCode = async () => {
  if (userB.value.bound && !bindings.value.length) return
  try {
    const r = await GET('/notifications/tg/bind-link')
    bindLink.value = r.url
    bindCommand.value = r.command || ''
    renderWidget(r.bot_username)
  } catch {}
}

// Login Widget（需 bot 在 BotFather 绑定当前域名；tovaads.com 已绑）
const renderWidget = (botUsername) => {
  if (!botUsername) return
  nextTick(() => {
    const el = document.getElementById('tg-widget')
    if (!el || el.firstChild) return
    const s = document.createElement('script')
    s.src = 'https://telegram.org/js/telegram-widget.js?22'
    s.setAttribute('data-telegram-login', botUsername)
    s.setAttribute('data-size', 'large')
    s.setAttribute('data-radius', '8')
    s.setAttribute('data-onauth', 'onTelegramAuth(user)')
    el.appendChild(s)
    window.onTelegramAuth = async (u) => {
      try {
        await POST('/notifications/tg/oauth-callback', u)
        ElMessage.success(t('tg.boundToast'))
        await load()
      } catch (e) { ElMessage.error(e.message || t('tg.opFail')) }
    }
  })
}

// 复制命令 = 现拉新码再复制（永不过期），并轮询绑定结果
const copyCmd = async () => {
  await refreshCode()
  if (!bindCommand.value) return
  try { await navigator.clipboard.writeText(bindCommand.value); ElMessage.success(t('tg.cmdCopied')) } catch {}
  startPoll()
}
const openLink = () => { startPoll() }

let _poll = null
const startPoll = () => {
  waiting.value = true
  if (_poll) return
  _poll = setInterval(async () => {
    try {
      const r = await GET('/notifications/tg/user-binding')
      if (r?.bound) {
        stopPoll()
        userB.value = r
        ElMessage.success(t('tg.boundToast'))
        tab.value = 'mine'
      }
    } catch {}
  }, 5000)
  setTimeout(stopPoll, 180000)
}
const stopPoll = () => { waiting.value = false; if (_poll) { clearInterval(_poll); _poll = null } }
onUnmounted(stopPoll)

const unbind = async (b) => {
  try {
    await ElMessageBox.confirm(t('tg.unbindConfirm', { id: b.chat_id_masked }), t('tg.unbind'), { type: 'warning', confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
  } catch { return }
  try {
    await DELETE(`/notifications/tg/user-binding?chat_id=${encodeURIComponent(b.chat_id)}`)
    ElMessage.success(t('tg.unbound'))
    await load()
  } catch (e) { ElMessage.error(e.message || t('tg.opFail')) }
}

const sendTest = async () => {
  try {
    const r = await POST('/notifications/tg/user-test')
    ElMessage.success(t('tg.testSent', { n: r.sent ?? r.status === 'sent' ? 1 : 0 }))
  } catch (e) { ElMessage.error(e.message || t('tg.opFail')) }
}

const bindManual = async () => {
  if (!manual.value.chat_id.trim()) return
  manual.value.saving = true
  try {
    await POST('/notifications/tg/user-binding', { bot_token: '', chat_id: manual.value.chat_id.trim() })
    ElMessage.success(t('tg.boundToast'))
    manual.value.chat_id = ''
    await load()
    tab.value = 'mine'
  } catch (e) { ElMessage.error(e.message || t('tg.opFail')) }
  manual.value.saving = false
}

const loadTeam = async () => {
  if (team.value.members.length || team.value.loading) return
  team.value.loading = true
  try { team.value.members = (await GET('/notifications/tg/team-bindings')).members || [] }
  catch { team.value.members = [] }
  team.value.loading = false
}

watch(tab, (v) => { if (v === 'team') loadTeam() })

const open = () => { dlgOpen.value = true; tab.value = userB.value.bound ? 'mine' : 'add'; load() }
const close = () => { dlgOpen.value = false; stopPoll() }
defineExpose({ open, close, load })
load()
</script>

<template>
  <el-dialog v-model="dlgOpen" :title="t('tg.title')" width="620px" @close="close" class="tg-dlg">
    <div class="tg-mgr">
      <div class="tg-tabs">
        <button class="tg-tab" :class="{ on: tab === 'mine' }" @click="tab = 'mine'">{{ t('tg.tabMine') }}<span v-if="bindings.length" class="cnt">{{ bindings.length }}</span></button>
        <button class="tg-tab" :class="{ on: tab === 'add' }" @click="tab = 'add'; refreshCode()">{{ t('tg.tabAdd') }}</button>
        <button v-if="canManage" class="tg-tab" :class="{ on: tab === 'team' }" @click="tab = 'team'">{{ t('tg.tabTeam') }}</button>
      </div>

      <div v-if="loading" class="tg-empty">{{ t('common.loading') }}</div>

      <!-- 我的绑定 -->
      <div v-else-if="tab === 'mine'">
        <div v-if="!bindings.length" class="tg-empty">
          {{ t('tg.noneYet') }}
          <div><button class="btn primary" @click="tab = 'add'; refreshCode()">{{ t('tg.bindNow') }}</button></div>
        </div>
        <div v-else class="tg-list">
          <div v-for="b in bindings" :key="b.id" class="tg-row">
            <div class="tg-row-main">
              <span class="tg-badge">✅ Telegram {{ b.chat_id_masked }}</span>
              <span class="tg-row-sub">
                {{ b.verified ? t('tg.verifiedAt', { ts: fmtTs(b.verified_at || b.created_at) }) : t('tg.unverified') }}
                <template v-if="b.created_at"> · {{ t('tg.boundAt', { ts: fmtTs(b.created_at) }) }}</template>
              </span>
            </div>
            <button class="btn" @click="unbind(b)">{{ t('tg.unbind') }}</button>
          </div>
          <div class="tg-actions">
            <button class="btn" @click="sendTest">{{ t('tg.sendTest') }}</button>
            <button class="btn primary" @click="tab = 'add'; refreshCode()">{{ t('tg.addAnother') }}</button>
          </div>
          <div class="tg-note">{{ t('tg.multiNote') }}</div>
        </div>
      </div>

      <!-- 添加绑定 -->
      <div v-else-if="tab === 'add'">
        <div class="tg-step"><span class="n">1</span>{{ t('tg.step1') }}</div>
        <a v-if="bindLink" :href="bindLink" target="_blank" rel="noopener" class="btn primary tg-big" @click="openLink">{{ t('tg.openTg') }}</a>
        <div class="tg-cmd-row">
          <code v-if="bindCommand">{{ bindCommand }}</code>
          <button class="btn" @click="copyCmd">{{ t('tg.copyCmd') }}</button>
        </div>
        <div class="tg-hint">{{ t('tg.cmdHint') }}</div>
        <div class="tg-step"><span class="n">2</span>{{ t('tg.step2') }}</div>
        <div v-if="waiting" class="tg-waiting">{{ t('tg.waiting') }}</div>
        <div v-if="botInfo.bot_username" id="tg-widget" class="tg-widget"></div>
        <details class="tg-fold">
          <summary>{{ t('tg.manualFold') }}</summary>
          <div class="tg-fold-row">
            <input v-model="manual.chat_id" class="input" :placeholder="t('tg.manualPh')" @keyup.enter="bindManual" />
            <button class="btn" :disabled="manual.saving" @click="bindManual">{{ manual.saving ? t('common.saving') : t('tg.manualBind') }}</button>
          </div>
          <div class="tg-hint">{{ t('tg.manualHint') }}</div>
        </details>
        <div v-if="!botInfo.configured" class="tg-hint" style="color: var(--el-color-danger, #f56c6c)">{{ t('tg.botNotConfigured') }}</div>
      </div>

      <!-- 团队成员清单 -->
      <div v-else-if="tab === 'team'">
        <div v-if="team.loading" class="tg-empty">{{ t('common.loading') }}</div>
        <div v-else-if="!team.members.length" class="tg-empty">{{ t('tg.teamEmpty') }}</div>
        <table v-else class="tg-team">
          <thead><tr><th>{{ t('tg.colUser') }}</th><th>{{ t('tg.colRole') }}</th><th>{{ t('tg.colTg') }}</th></tr></thead>
          <tbody>
            <tr v-for="m in team.members" :key="m.user_id">
              <td>{{ m.email }}<span v-if="m.is_me" class="me">{{ t('tg.meTag') }}</span></td>
              <td>{{ m.role }}</td>
              <td :class="{ zero: !m.tg_count }">
                {{ m.tg_count ? m.chat_ids_masked.join('、') : t('tg.noBinding') }}
                <template v-if="m.tg_count > 1">（{{ m.tg_count }}）</template>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="tg-note">{{ t('tg.teamNote') }}</div>
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
.tg-mgr { min-height: 200px; }
.tg-tabs { display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
.tg-tab { border: 1px solid var(--bd); background: var(--bg); border-radius: 8px; padding: 7px 14px; cursor: pointer; font-size: 13px; color: var(--tx-2, #555); }
.tg-tab.on { background: var(--el-color-primary, #409eff); border-color: var(--el-color-primary, #409eff); color: #fff; }
.tg-tab .cnt { display: inline-block; min-width: 16px; padding: 0 4px; margin-left: 4px; border-radius: 8px; background: rgba(127,127,127,.18); font-size: 11px; text-align: center; }
.tg-empty { padding: 26px 10px; text-align: center; color: var(--tx-3, #999); font-size: 13px; }
.tg-empty .btn { margin-top: 10px; }
.tg-list { display: flex; flex-direction: column; gap: 8px; }
.tg-row { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--bd); border-radius: 10px; }
.tg-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.tg-badge { font-weight: 600; font-size: 13px; }
.tg-row-sub { font-size: 12px; color: var(--tx-3, #999); }
.tg-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.tg-note { margin-top: 8px; font-size: 12px; color: var(--tx-3, #999); }
.tg-step { font-size: 13px; margin: 10px 0 8px; display: flex; gap: 8px; align-items: center; }
.tg-step .n { flex: none; width: 20px; height: 20px; border-radius: 50%; background: var(--el-color-primary, #409eff); color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; }
.tg-big { display: block; text-align: center; padding: 10px 16px; font-size: 14px; }
.tg-cmd-row { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
.tg-cmd-row code { flex: 1; min-width: 200px; padding: 8px 10px; background: var(--bg-2, #f5f5f5); border: 1px solid var(--bd); border-radius: 8px; font-size: 12px; word-break: break-all; user-select: all; }
.tg-hint { font-size: 12px; color: var(--tx-3, #999); margin-top: 6px; line-height: 1.5; }
.tg-waiting { margin-top: 10px; font-size: 12px; color: var(--el-color-primary, #409eff); }
.tg-widget { margin-top: 12px; min-height: 36px; }
.tg-fold { margin-top: 14px; border-top: 1px dashed var(--bd); padding-top: 10px; }
.tg-fold summary { font-size: 12px; color: var(--tx-3, #999); cursor: pointer; }
.tg-fold-row { display: flex; gap: 8px; margin-top: 8px; }
.tg-fold-row input { flex: 1; min-width: 0; }
.tg-team { width: 100%; border-collapse: collapse; font-size: 13px; }
.tg-team th, .tg-team td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--bd); }
.tg-team th { font-weight: 600; color: var(--tx-3, #888); font-size: 12px; }
.tg-team .me { color: var(--el-color-primary, #409eff); font-size: 11px; margin-left: 4px; }
.tg-team .zero { color: var(--el-color-danger, #f56c6c); }
@media (max-width: 560px) { .tg-cmd-row code { min-width: 120px; } }
</style>
