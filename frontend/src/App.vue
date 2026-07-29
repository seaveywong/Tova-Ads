<script setup>
import { RouterView } from 'vue-router'
import { useLocale } from './composables/useLocale'
const { epLocale } = useLocale()
</script>

<template>
  <el-config-provider :locale="epLocale">
    <RouterView />
  </el-config-provider>
</template>
