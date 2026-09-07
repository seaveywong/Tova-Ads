# 批H续：LaunchTemplates 平铺移除 + FB 强制结构 + lifetime 免日预算 + 复用帖预填转结构
import io, re
edits = []
p = "frontend/src/views/LaunchTemplates.vue"
s = io.open(p, encoding="utf-8").read()

# 1. 整块移除模式切换容器（注释+wrapper div+label+radio）
m = re.search(r'[ ]*<!-- 编辑模式[\s\S]{0,260}?</el-radio-group>\s*</div>\n', s)
assert m, "mode_row"
s = s.replace(m.group(0), "", 1); edits.append("mode_row_removed")

# 2. 抽出无确认的平铺→树合成 helper（onModeSwitch 里那段复用）
anchor = "const onModeSwitch = async (nv) => {"
i = s.index(anchor)
helper = '''const _synthTreeFromFlat = () => {
  const s = blankTreeAdset()
  s.audience_id = form.value.audience_id || 0
  s.optimization_goal = form.value.optimization_goal || ''
  s.billing_event = form.value.billing_event || ''
  s.ads = [adFromFlat()]
  tree.value = { adsets: [s] }
  expandAllTree(); ensureTreeAssets()
  expandedAdKeys.value = new Set(tree.value.adsets.flatMap(x => (x.ads || []).map(a => a.key)))
  editMode.value = 'tree'
}
'''
s = s[:i] + helper + s[i:]; edits.append("synth_helper")

# 3. openEdit：FB 无 structure 也强制转结构（平铺模式 UI 移除，旧模板自动升级视图）
old = '''  validationErrors.value = []; editOpen.value = true; snapshotForm()
}
const pickAsset = async (a) => {'''
assert old in s, "openedit_tail"
new = '''  // FB 模板一律结构模式（平铺模式已移除；无 structure 的旧模板自动合成 1 组 1 广告视图，保存即升级）
  if (!isTt.value && editMode.value === 'flat') _synthTreeFromFlat()
  validationErrors.value = []; editOpen.value = true; snapshotForm()
}
const pickAsset = async (a) => {'''
s = s.replace(old, new, 1); edits.append("openedit_force_tree")

# 4. 跟帖预填流（Ads 页复用此帖）：填完平铺字段后转结构（广告节点带跟帖引用）
old = '''    form.value.page_id = String(rp).split('_')[0]  // {page}_{post} → page
    fetchReusePreview(String(rp))  // 拉帖子内容预览
    snapshotForm()  // 重新快照（含预填值，避免一开就标 dirty）'''
assert old in s, "reuse_prefill"
new = '''    form.value.page_id = String(rp).split('_')[0]  // {page}_{post} → page
    fetchReusePreview(String(rp))  // 拉帖子内容预览
    _synthTreeFromFlat()   // 平铺模式已移除：预填值合成结构树（首广告节点=跟帖）
    snapshotForm()  // 重新快照（含预填值，避免一开就标 dirty）'''
s = s.replace(old, new, 1); edits.append("reuse_prefill_tree")

# 5. lifetime 免日预算（对齐后端 bf3cfd0）：日预算必填仅 daily 模式
old = '''  if (!form.value.budget_usd || Number(form.value.budget_usd) <= 0) errs.push(t('launch.fieldDailyBudget'))
  if (Number(form.value.budget_usd) > 5000) errs.push(t('launch.fieldBudgetCap', { n: 5000 }))'''
assert old in s, "budget_req"
new = '''  if (form.value.budget_type !== 'lifetime') {
    if (!form.value.budget_usd || Number(form.value.budget_usd) <= 0) errs.push(t('launch.fieldDailyBudget'))
    if (Number(form.value.budget_usd) > 5000) errs.push(t('launch.fieldBudgetCap', { n: 5000 }))
  }'''
s = s.replace(old, new, 1); edits.append("lifetime_no_daily")

io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("H2:", edits)
