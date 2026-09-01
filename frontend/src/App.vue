<script setup>
import { RouterView } from 'vue-router'
import { useLocale } from './composables/useLocale'
import { prefetchRoutes } from './router'
const { epLocale } = useLocale()
prefetchRoutes()
</script>

<template>
  <el-config-provider :locale="epLocale">
    <RouterView />
  </el-config-provider>
</template>
