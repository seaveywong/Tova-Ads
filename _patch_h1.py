# 批H：用户反馈五连修
import io
edits = []

# ── 1. 后端：巡检跳过原因人话化（保留 insights失败 前缀标记——guard_engine 1927 行按它统计）──
p = "backend/app/services/guard_engine.py"
s = io.open(p, encoding="utf-8").read()
old = '''            res["skip_reasons"].append(f"{acc.name}({acc.act_id}): insights失败-{e.category or '未知'}")'''
new = '''            # 原因人话化（用户反馈：insights失败-permissions 看不懂为什么没巡检）。
            # 保留 "insights失败-" 前缀——主循环按它统计 fetch_fail 数量，别动标记。
            _HUMAN = {
                "permissions": "令牌权限不足（该账户绑定的令牌已移除或未授权读取，请到令牌页核查/重新授权）",
                "token_expired": "令牌已失效（请到令牌页重新授权）",
                "rate_limited": "令牌限流（自动恢复）",
                "no_id": "无可用令牌（该账户未绑定任何令牌）",
                "network": "网络错误",
                "account_checkpoint": "账户安全锁定（需号主本人验证）",
            }
            _why = _HUMAN.get(e.category or "", e.category or "未知")
            res["skip_reasons"].append(f"{acc.name}({acc.act_id}): insights失败-{_why}")'''
assert old in s, "guard"; s = s.replace(old, new, 1); edits.append("guard_human")
io.open(p, "w", encoding="utf-8", newline="\n").write(s)

# ── 2. FormTemplates.vue：双加号修复 + 卡片加「删除」（接现成 DELETE 端点）──
p = "frontend/src/views/FormTemplates.vue"
s = io.open(p, encoding="utf-8").read()
old = '''        <button v-if="tab==='form'" class="head-btn primary" @click="formPlatDialog = true">+ {{ t('formtpl.newBtn', { kind: t('formtpl.formUnit') }) }}</button>'''
new = '''        <button v-if="tab==='form'" class="head-btn primary" @click="formPlatDialog = true">{{ t('formtpl.newBtn', { kind: t('formtpl.formUnit') }) }}</button>'''
assert old in s, "doubleplus"; s = s.replace(old, new, 1); edits.append("doubleplus")

# 删除函数（表单+消息，接现成端点；确认弹窗强调 FB 侧已建表单不受影响）
anchor = "const removeForm = async (item) => {"
i = s.index(anchor)
inject = '''const hardDelete = async (item, kind) => {
  const tip = kind === 'form' ? t('formtpl.delConfirm', { name: item.name }) : t('formtpl.delMsgConfirm', { name: item.name })
  try { await ElMessageBox.confirm(tip, t('common.confirm'), { type: 'warning', confirmButtonClass: 'el-button--danger' }) } catch { return }
  try {
    await DELETE(kind === 'form' ? '/form-templates/forms/' + item.id : '/form-templates/messages/' + item.id)
    ElMessage.success(t('common.savedOk'))
    if (kind === 'form') { forms.value = forms.value.filter(x => x.id !== item.id) }
    else { msgs.value = msgs.value.filter(x => x.id !== item.id) }
  } catch (e) { ElMessage.error(e.message || t('common.opFail')) }
}
'''
s = s[:i] + inject + s[i:]
edits.append("del_fn")

# 卡片操作行加删除按钮：找 归档/removeForm 调用与 removeMsg 调用按钮
import re
m = re.search(r'(@click="removeForm\([^)]*\)"[^<]*</button>)', s)
assert m, "form_arc_btn"
s = s.replace(m.group(1), m.group(1) + '''<button class="op sm" style="color:var(--error)" @click="hardDelete(item, 'form')">{{ t('common.delete') }}</button>''', 1)
edits.append("form_del_btn")
m2 = re.search(r'(@click="removeMsg\([^)]*\)"[^<]*</button>|@click="removeForm\(m\)[^<]*</button>)', s)
if m2:
    s = s.replace(m2.group(1), m2.group(1) + '''<button class="op sm" style="color:var(--error)" @click="hardDelete(m, 'msg')">{{ t('common.delete') }}</button>''', 1)
    edits.append("msg_del_btn")
io.open(p, "w", encoding="utf-8", newline="\n").write(s)

# ── 3. LaunchTemplates.vue：FB 模板平铺模式移除（TT 保留平铺）──
p = "frontend/src/views/LaunchTemplates.vue"
s = io.open(p, encoding="utf-8").read()
# 3a. 整块移除模式切换容器（wrapper div + label + radio 全块）
m = re.search(r'[ ]*<!-- 编辑模式[\s\S]{0,60}?tpl-mode-row">[\s\S]{0,420}?</div>\n', s)
assert m, "mode_row"
s = s.replace(m.group(0), "", 1)
edits.append("mode_row_removed")
print("H1:", edits)
