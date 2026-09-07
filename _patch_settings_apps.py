import io, re
edits = []

# ── Settings.vue：两个新分区（FB App 配置 + 导入行为）──
p = "frontend/src/views/Settings.vue"
s = io.open(p, encoding="utf-8").read()

# 分区清单注册（sec-webhook 后）
old = "    secs.push({ id: 'sec-webhook', label: t('settings.whTitle') })"
new = """    secs.push({ id: 'sec-webhook', label: t('settings.whTitle') })
    secs.push({ id: 'sec-fbapps', label: t('settings.faTitle') })
    secs.push({ id: 'sec-import', label: t('settings.ibTitle') })"""
assert old in s, "sections"
s = s.replace(old, new, 1)
edits.append("sections")

# script 状态+函数（追加在 webhook 相关函数后——找 webhook 配置加载函数锚）
anchor = "const whCfg = ref("
assert anchor in s
# 在 script 的某个稳定位置插：找 onMounted 或最后一个 const 声明块。用 whSave 之类锚定后插。
m = re.search(r'\nconst \w+ = async \(\) => \{[^}]*webhook[^}]*\}', s)
# 简化：在 anchorSections computed 前插入
anchor2 = "// ── 锚点导航（sticky 横条，点跳对应卡片；滚动高亮当前区）──"
assert anchor2 in s
inject = """// ── FB App 配置管理（重建入口：列表/新建/改 secret/删除——OAuth 授权与 webhook 验签依赖）──
const faApps = ref([])
const faLoading = ref(false)
const faEditId = ref(null)   // null=新建
const faForm = ref({ name: '', app_id: '', app_secret: '', is_system: false })
const faDialog = ref(false)
const faSaving = ref(false)
const isSuper = ref((window.localStorage.getItem('tova_perms') || '').includes('superadmin'))
const loadFaApps = async () => {
  faLoading.value = true
  try { faApps.value = (await GET('/fb-apps')) || [] }
  catch (e) { faApps.value = []; ElMessage.error(e.message || t('common.fail')) }
  faLoading.value = false
}
const faOpenNew = () => { faEditId.value = null; faForm.value = { name: '', app_id: '', app_secret: '', is_system: false }; faDialog.value = true; loadFaApps() }
const faOpenEdit = (a) => { faEditId.value = a.id; faForm.value = { name: a.name || '', app_id: a.app_id, app_secret: '', is_system: !!a.is_system }; faDialog.value = true }
const faSave = async () => {
  if (!faForm.value.app_id.trim() || (!faForm.value.app_secret.trim() && !faEditId.value)) return ElMessage.warning(t('settings.faFillBoth'))
  faSaving.value = true
  try {
    const body = { ...faForm.value, name: faForm.value.name.trim(), app_id: faForm.value.app_id.trim(), app_secret: faForm.value.app_secret }
    if (faEditId.value) await POST(`/fb-apps/${faEditId.value}`, body)
    else await POST('/fb-apps', body)
    faDialog.value = false
    ElMessage.success(t('common.savedOk'))
    await loadFaApps()
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  faSaving.value = false
}
const faDelete = async (a) => {
  try { await ElMessageBox.confirm(t('settings.faDeleteConfirm', { id: a.app_id }), t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }) } catch { return }
  try { await DELETE(`/fb-apps/${a.id}`); ElMessage.success(t('common.savedOk')); await loadFaApps() }
  catch (e) { ElMessage.error(e.message || t('common.opFail')) }
}

// ── 账户导入行为（超管统一入口：默认全选 + 新令牌默认上限）──
const ibCfg = ref({ import_default_all: false, import_default_cap: 100 })
const ibCapInput = ref('100')
const ibAll = ref(false)
const ibSaving = ref(false)
const loadIb = async () => {
  try {
    ibCfg.value = await GET('/settings/import-behavior')
    ibAll.value = !!ibCfg.value.import_default_all
    ibCapInput.value = String(ibCfg.value.import_default_cap ?? 100)
  } catch { /* 非超管 403 → 卡片隐藏 */ }
}
const saveIb = async () => {
  const cap = parseInt(ibCapInput.value, 10)
  if (isNaN(cap) || cap < 0 || cap > 10000) return ElMessage.warning(t('settings.ibCapLimit'))
  ibSaving.value = true
  try {
    ibCfg.value = await PUT('/settings/import-behavior', { import_default_all: ibAll.value, import_default_cap: cap })
    ElMessage.success(t('common.savedOk'))
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
  ibSaving.value = false
}

"""
s = s.replace(anchor2, inject + anchor2, 1)
edits.append("script fns")

# 模板：找 sec-webhook 分区结尾后插两个新分区（v-if 各自权限）
m = re.search(r"activeSection === 'sec-webhook'", s)
assert m, "webhook template"
# 找该分区的闭合：取模板里 webhook section 块结尾 </section> 或 </div>——用「下一个 section 开始前」策略：
# 插到 webhook section 结束后。定位：'sec-webhook' 出现的模板段
m2 = re.search(r"(activeSection === 'sec-webhook'[\s\S]{0,6000}?)(\n\s*)(<section|<div v-if=\"activeSection)", s)
if not m2:
    # webhook 是最后一个分区：直接在 settings 容器闭合前插。找 anchor-strip 对应内容区结束
    m3 = re.search(r'(\n\s*)</div>\s*\n\s*</template>', s)
    assert m3, "template end"
    tpl = """
    <section v-if="activeSection === 'sec-fbapps'" class="settings-section">
      <h3 class="sec-title">{{ t('settings.faTitle') }}</h3>
      <p class="sec-desc">{{ t('settings.faDesc') }}</p>
      <div v-loading="faLoading" class="fa-list">
        <div v-for="a in faApps" :key="a.id" class="fa-row">
          <div class="fa-info">
            <span class="fa-name">{{ a.name || a.app_id }}</span>
            <code class="fa-id">{{ a.app_id }}</code>
            <span v-if="a.is_system" class="st-tag off">{{ t('settings.faSystem') }}</span>
          </div>
          <div class="fa-ops">
            <button class="ctrl-btn sm" @click="faOpenEdit(a)">{{ t('common.edit') }}</button>
            <button class="ctrl-btn sm" style="color: var(--error)" @click="faDelete(a)">{{ t('common.delete') }}</button>
          </div>
        </div>
        <div v-if="!faApps.length && !faLoading" class="empty">{{ t('settings.faEmpty') }}</div>
      </div>
      <button class="btn primary" @click="faOpenNew()">{{ t('settings.faAdd') }}</button>
      <el-dialog v-model="faDialog" :title="faEditId ? t('common.edit') : t('settings.faAdd')" width="420px" append-to-body>
        <div class="rd-form">
          <label>{{ t('settings.faName') }}</label>
          <input v-model.trim="faForm.name" class="budget-input" :placeholder="t('settings.faNamePh')" />
          <label>{{ t('settings.faAppId') }}</label>
          <input v-model.trim="faForm.app_id" class="budget-input" placeholder="1234567890" />
          <label>{{ t('settings.faSecret') }}</label>
          <input v-model.trim="faForm.app_secret" type="password" class="budget-input" :placeholder="faEditId ? t('settings.faSecretKeep') : 'app_secret'" />
          <label v-if="isSuper" class="fa-sys"><input type="checkbox" v-model="faForm.is_system" /> {{ t('settings.faSystemOpt') }}</label>
        </div>
        <template #footer>
          <button class="ctrl-btn" @click="faDialog = false">{{ t('common.cancel') }}</button>
          <button class="ctrl-btn primary" :disabled="faSaving" @click="faSave">{{ faSaving ? t('common.saving') : t('common.save') }}</button>
        </template>
      </el-dialog>
    </section>
    <section v-if="activeSection === 'sec-import'" class="settings-section">
      <h3 class="sec-title">{{ t('settings.ibTitle') }}</h3>
      <p class="sec-desc">{{ t('settings.ibDesc') }}</p>
      <div class="ib-form">
        <label class="ib-row"><input type="checkbox" v-model="ibAll" /> {{ t('settings.ibAllLabel') }}</label>
        <label class="ib-row">{{ t('settings.ibCapLabel') }}<input v-model.trim="ibCapInput" class="budget-input ib-cap" :placeholder="t('settings.ibCapPh')" /></label>
        <p class="sec-desc">{{ t('settings.ibCapNote') }}</p>
        <button class="btn primary" :disabled="ibSaving" @click="saveIb">{{ ibSaving ? t('common.saving') : t('common.save') }}</button>
      </div>
    </section>"""
    s = s[:m3.start(1)] + tpl + s[m3.start(1):]
    edits.append("template sections")
else:
    raise SystemExit("need manual placement")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("Settings.vue:", edits)

# ── Tokens.vue：openLoad 按配置默认全选未导入 ──
p = "frontend/src/views/Tokens.vue"
s = io.open(p, encoding="utf-8").read()
import re as _re
m = _re.search(r'const openLoad = async \(\) => \{[\s\S]{0,700}?\n\}', s)
print("openLoad:", m.group(0)[:300] if m else None)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
