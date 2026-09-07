import io, re
p = "views/Tokens.vue"
s = io.open(p, encoding="utf-8").read()
edits = []

# 1) 裸键 tt${...} 修 type 前缀
old = """{{ t(`tokens.tt${tk.token_type || 'manage'}`) }} → {{ t(`tokens.tt${(tk.token_type || 'manage') === 'operate' ? 'manage' : 'operate'}`) }}"""
new = """{{ t(`tokens.type${(tk.token_type || 'manage')[0].toUpperCase() + (tk.token_type || 'manage').slice(1)}`) }} → {{ t(`tokens.type${((tk.token_type || 'manage') === 'operate' ? 'manage' : 'operate')[0].toUpperCase() + ...}`) }}"""
# 太绕——直接 JS helper。改为：
new = """{{ ttTypeLabel(tk.token_type) }} → {{ ttTypeLabel((tk.token_type || 'manage') === 'operate' ? 'manage' : 'operate') }}"""
assert old in s, "tt key"
s = s.replace(old, new, 1)
edits.append("tt key fix")

# helper
anchor = "const changeTokenType = async (tk) => {"
helper = """const ttTypeLabel = (ty) => {
  const k = ty || 'manage'
  return t(`tokens.type${k[0].toUpperCase() + k.slice(1)}`)
}
"""
s = s.replace(anchor, helper + anchor, 1)

# 2) 导入 >50 确认（doImport 前）
old = """const doImport = async (ids) => {
  loadImporting.value = true"""
new = """const doImport = async (ids) => {
  // 导入保护（>50 确认一次——几千账户一次进来炸巡检/同步）
  if (ids.length > 50) {
    try {
      await ElMessageBox.confirm(t('tokens.importBigBatchConfirm', { n: ids.length }), t('common.confirm'), { type: 'warning' })
    } catch { return }
  }
  loadImporting.value = true"""
assert old in s, "import confirm"
s = s.replace(old, new, 1)
edits.append(">50 confirm")

# 3) TT 导入同样确认
old = """const commitTtLoad = async () => {
  const ids = Object.keys(ttLoadSelected.value).filter(k => ttLoadSelected.value[k])
  if (!ids.length) { ElMessage.warning(t('tokens.selectUnimported')); return }
  ttLoadImporting.value = true"""
new = """const commitTtLoad = async () => {
  const ids = Object.keys(ttLoadSelected.value).filter(k => ttLoadSelected.value[k])
  if (!ids.length) { ElMessage.warning(t('tokens.selectUnimported')); return }
  if (ids.length > 50) {
    try {
      await ElMessageBox.confirm(t('tokens.importBigBatchConfirm', { n: ids.length }), t('common.confirm'), { type: 'warning' })
    } catch { return }
  }
  ttLoadImporting.value = true"""
assert old in s, "tt confirm"
s = s.replace(old, new, 1)
edits.append("tt >50 confirm")

# 4) 主页改类型函数（renamePage 旁）
anchor = "const changeTokenType = async (tk) => {"
fn = """const setPageCategory = async (tk, p) => {
  try {
    const { value } = await ElMessageBox.prompt(
      t('tokens.pageCategoryPrompt'), t('tokens.categoryBtn'),
      { inputValue: p.category || '', inputPattern: /^.{1,120}$/, inputErrorMessage: t('tokens.pageCategoryLimit'),
        confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
    await POST(`/fb/credentials/${tk.id}/pages/category`, { page_id: p.id, category: value.trim() })
    ElMessage.success(t('tokens.pageCategorySaved'))
    if (drawerToken.value) await loadDrawerAssets(drawerToken.value)
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}
"""
s = s.replace(anchor, fn + anchor, 1)
edits.append("setPageCategory fn")

# 5) 主页行菜单加改类型入口
old = """<el-dropdown-item @click="renamePage(drawerToken, p)">{{ t('tokens.renameBtn') }}</el-dropdown-item>"""
new = """<el-dropdown-item @click="renamePage(drawerToken, p)">{{ t('tokens.renameBtn') }}</el-dropdown-item>
                    <el-dropdown-item @click="setPageCategory(drawerToken, p)">{{ t('tokens.categoryBtn') }}</el-dropdown-item>"""
assert old in s, "menu"
s = s.replace(old, new, 1)
edits.append("menu entry")

# 6) 令牌上限编辑（抽屉：token-type 展示旁。找 drawer 里显示 token_type 的地方加行）——找 drawer 详情区
m = re.search(r'(\n\s*)<span class="st-tag[^"]*">\{\{ tk\.token_type[^<]*</span>', s)
# 简化：在 changeTokenType 菜单下加 set_max_accounts 命令
old = "  else if (cmd === 'change_type') changeTokenType(tk)"
new = """  else if (cmd === 'change_type') changeTokenType(tk)
  else if (cmd === 'max_accounts') changeMaxAccounts(tk)"""
assert old in s, "dispatch"
s = s.replace(old, new, 1)

fn2 = """const changeMaxAccounts = async (tk) => {
  try {
    const cur = tk.max_accounts == null ? '' : String(tk.max_accounts)
    const { value } = await ElMessageBox.prompt(
      t('tokens.maxAccountsPrompt', { cur: tk.max_accounts == null ? t('tokens.maxAccountsUnlimited') : tk.max_accounts, n: tk.account_count ?? 0 }),
      t('tokens.maxAccountsBtn'),
      { inputValue: cur, inputPattern: /^$|^\\d{1,5}$/, inputErrorMessage: t('tokens.maxAccountsLimit'),
        confirmButtonText: t('common.confirm'), cancelButtonText: t('common.cancel') })
    const v = value.trim() === '' ? null : parseInt(value.trim(), 10)
    await PUT(`/fb/credentials/${tk.id}/max-accounts`, { max_accounts: v })
    ElMessage.success(t('common.savedOk'))
    await load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}
"""
s = s.replace(anchor, fn2 + anchor, 1)
edits.append("changeMaxAccounts")

old = """<el-dropdown-item command="change_type" divided>"""
new = """<el-dropdown-item command="max_accounts">📊 {{ t('tokens.maxAccountsBtn') }}</el-dropdown-item>
                <el-dropdown-item command="change_type" divided>"""
assert old in s, "menu2"
s = s.replace(old, new, 1)
edits.append("menu entry 2")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("Tokens.vue:", edits)

# i18n
p = "locales/zh.js"
s = io.open(p, encoding="utf-8").read()
old = "    renameBtn: '改名',"
new = """    renameBtn: '改名', categoryBtn: '改类型', pageCategoryPrompt: '新的主页类别（如 Internet Marketing Service，将真实修改 FB 主页类型；需主页管理权限）', pageCategoryLimit: '1-120 字符', pageCategorySaved: '主页类别已更新',
    maxAccountsBtn: '账户数上限', maxAccountsPrompt: '该令牌最多绑定多少个账户（当前已绑 {n} 个，现为 {cur}）。留空 = 不限。操作号建议 ≤100，防一个号带几千账户炸巡检。', maxAccountsLimit: '留空或 1-5 位数字', maxAccountsUnlimited: '不限',
    importBigBatchConfirm: '本次将导入 {n} 个账户——大量账户会显著增加巡检耗时与 API 消耗，且操作号有绑定上限（超额账户会被跳过）。确定继续？',"""
assert old in s
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)

p = "locales/en.js"
s = io.open(p, encoding="utf-8").read()
old = "    renameBtn: 'Rename',"
assert old in s
new = """    renameBtn: 'Rename', categoryBtn: 'Change Category', pageCategoryPrompt: 'New page category (e.g. "Internet Marketing Service"). Requires page manage permission.', pageCategoryLimit: '1-120 chars', pageCategorySaved: 'Page category updated',
    maxAccountsBtn: 'Account Cap', maxAccountsPrompt: 'Max accounts this token may bind (currently {n} bound, limit: {cur}). Empty = unlimited. Operate tokens advised ≤100.', maxAccountsLimit: 'Empty or 1-5 digits', maxAccountsUnlimited: 'unlimited',
    importBigBatchConfirm: 'You are about to import {n} accounts — large batches increase inspection time & API usage, and token caps may skip some. Continue?',"""
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("i18n ok")
