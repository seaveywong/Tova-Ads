<script setup>
import { RouterView } from 'vue-router'
import { useLocale } from './composables/useLocale'
const { epLocale } = useLocale()
// 路由 chunk 预取在 MainLayout（登录后的主壳）里做，登录页不拉
</script>

<template>
  <el-config-provider :locale="epLocale">
    <RouterView />
  </el-config-provider>
</template>
