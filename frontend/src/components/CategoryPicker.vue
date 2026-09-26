<script setup>
// 主页「改类型」选择器（可搜索 + 可自由输入）：替代原 ElMessageBox.prompt 自由文本盲猜
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { PAGE_CATEGORIES } from '../constants/pageCategories'
const { t } = useI18n()
const props = defineProps({
  modelValue: { type: Boolean, default: false },
  current: { type: String, default: '' },
  title: { type: String, default: '' },
  hint: { type: String, default: '' },
  placeholder: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'save'])
const val = ref('')
watch(() => props.modelValue, (v) => { if (v) val.value = props.current || '' })
const close = () => emit('update:modelValue', false)
const save = () => { emit('save', val.value.trim()); close() }
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="440px"
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-select
      v-model="val"
      filterable
      allow-create
      default-first-option
      :reserve-keyword="false"
      :placeholder="placeholder"
      style="width: 100%"
      @keyup.enter="save"
    >
      <el-option v-for="c in PAGE_CATEGORIES" :key="c" :label="c" :value="c" />
    </el-select>
    <div v-if="hint" class="cp-hint">{{ hint }}</div>
    <template #footer>
      <el-button @click="close">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" @click="save">{{ t('common.confirm') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cp-hint { margin-top: 10px; font-size: 12px; color: var(--t3); line-height: 1.5; }
</style>
