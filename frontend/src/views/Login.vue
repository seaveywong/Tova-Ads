<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api, setToken, GET } from '../api'
import { setUserPerms } from '../router'
import { ElMessage } from 'element-plus'

const router = useRouter()
const email = ref('')
const password = ref('')
const loading = ref(false)
const canLogin = computed(() => email.value.trim() && password.value)

const login = async () => {
  if (!email.value.trim() || !password.value) return ElMessage.warning('填邮箱和密码')
  loading.value = true
  try {
    const res = await api('POST', '/auth/login', { email: email.value, password: password.value })
    setToken(res.access_token)
    // 拉权限存 localStorage（导航过滤 + 路由守卫）
    try { const me = await GET('/auth/me'); setUserPerms(me.permissions || []) } catch {}
    router.push('/dashboard')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">Tova Ads</h1>
      <p class="login-sub">广告投放管理系统</p>
      <el-input v-model="email" placeholder="邮箱" class="login-input" @keyup.enter="login" />
      <el-input v-model="password" type="password" placeholder="密码" class="login-input" show-password @keyup.enter="login" />
      <el-button type="primary" class="login-btn" :loading="loading" :disabled="!canLogin" @click="login">登录</el-button>
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
}
.login-card {
  width: 360px;
  padding: 40px;
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
