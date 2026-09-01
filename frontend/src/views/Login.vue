<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { api, setToken, GET } from '../api'
import { setUserPerms } from '../router'
import { useLocale } from '../composables/useLocale'
import { ElMessage } from 'element-plus'

const { t } = useI18n()
const { locale, toggle: toggleLocale } = useLocale()
const router = useRouter()
const email = ref('')
const password = ref('')
const loading = ref(false)
const canLogin = computed(() => email.value.trim() && password.value)

const login = async () => {
  if (!email.value.trim() || !password.value) return ElMessage.warning(t('login.errFill'))
  loading.value = true
  try {
    const res = await api('POST', '/auth/login', { email: email.value, password: password.value })
    setToken(res.access_token)
    // 拉权限存 localStorage（导航过滤 + 路由守卫）+ 捕获 must_change_password（被邀新成员引导先改密）
    let mustChange = false
    try { const me = await GET('/auth/me'); setUserPerms(me.permissions || []); mustChange = !!me.must_change_password } catch {}
    if (mustChange) { ElMessage.warning(t('login.mustChangePwd')); router.push('/settings') }
    else router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <span class="lang-toggle" @click="toggleLocale"
          :title="locale === 'zh' ? t('layout.langToEn') : t('layout.langToZh')">
      {{ locale === 'zh' ? 'EN' : '中' }}
    </span>
    <div class="login-card">
      <h1 class="login-title">{{ t('login.title') }}</h1>
      <p class="login-sub">{{ t('login.subtitle') }}</p>
      <el-input v-model="email" :placeholder="t('login.emailPlaceholder')" class="login-input" autocomplete="username" @keyup.enter="login" />
      <el-input v-model="password" type="password" :placeholder="t('login.passwordPlaceholder')" class="login-input" autocomplete="current-password" show-password @keyup.enter="login" />
      <el-button type="primary" class="login-btn" :loading="loading" :disabled="!canLogin" @click="login">{{ t('login.signIn') }}</el-button>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
  position: relative;
}
.lang-toggle {
  position: absolute; top: 20px; right: 24px;
  font-size: 12px; font-weight: 700;
  padding: 4px 10px; border-radius: var(--rs);
  background: var(--bg3); color: var(--t2); cursor: pointer;
  user-select: none; transition: background 0.15s, color 0.15s;
}
.lang-toggle:hover { background: var(--acg); color: var(--ac); }
.login-card {
  width: min(360px, 92vw);
  padding: 32px 28px;
  background: var(--bg2);
  border-radius: var(--rs2);
  border: 1px solid var(--bd);
}
.login-title {
  font-size: 24px;
  color: var(--ac);
  margin-bottom: 4px;
}
.login-sub {
  font-size: 14px;
  color: var(--t3);
  margin-bottom: 28px;
}
.login-input {
  margin-bottom: 14px;
}
.login-btn {
  width: 100%;
  margin-top: 8px;
}
</style>
