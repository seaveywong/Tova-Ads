<script setup>
// 日期预设按钮条（Dashboard/Ads/AdManager 等页共用）。
// presets: [{key,label}]（useDateRange 的 DATE_PRESETS 或其子集）；
// modelValue = 当前 key；自定义区间由组件内部管理，apply 时 emit('custom',{from,to})，
// 切回预设 emit('update:modelValue', key)。
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  presets: { type: Array, required: true },
  modelValue: { type: String, default: '' },
  customLabel: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'preset', 'custom'])

const { t } = useI18n()
const showCustom = ref(false)
const customFrom = ref('')
const customTo = ref('')

const pick = (key) => {
  showCustom.value = false
  emit('update:modelValue', key)
  emit('preset', key)
}
const toggleCustom = () => { showCustom.value = !showCustom.value }
const applyCustom = () => {
  if (!customFrom.value || !customTo.value) return
  emit('custom', { from: customFrom.value, to: customTo.value })
}
const queryLabel = () => props.customLabel || t('common.search')
</script>

<template>
  <div class="date-bar">
    <button v-for="opt in presets" :key="opt.key" class="date-btn"
            :class="{ active: modelValue === opt.key && !showCustom }"
            @click="pick(opt.key)">{{ opt.label }}</button>
    <button class="date-btn" :class="{ active: showCustom }" @click="toggleCustom">{{ t('common.custom') }}</button>
    <Transition name="dpb">
      <div v-if="showCustom" class="custom-range">
        <input type="date" v-model="customFrom" class="date-input" /><span class="date-sep">—</span>
        <input type="date" v-model="customTo" class="date-input" />
        <button class="date-btn apply" @click="applyCustom">{{ queryLabel() }}</button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.date-bar { display: flex; gap: 4px; align-items: center; flex-wrap: wrap }
.date-btn { padding: 6px 14px; background: var(--bg2); color: var(--t2); border: 1px solid var(--bd); border-radius: var(--rs); font-size: 13px; cursor: pointer; transition: all 0.15s; font-family: inherit }
.date-btn:hover { color: var(--t1); border-color: var(--bd2) }
.date-btn.active { background: var(--ac); color: #fff; border-color: var(--ac) }
.date-btn.apply { background: var(--ac); color: #fff; border-color: var(--ac); margin-left: 4px }
.custom-range { display: flex; align-items: center; gap: 6px; margin-left: 8px }
.date-input { background: var(--bg3); color: var(--t1); border: 1px solid var(--bd); border-radius: var(--rs); padding: 5px 10px; font-size: 13px; color-scheme: dark; font-family: inherit }
.date-input:focus { outline: none; border-color: var(--ac) }
.date-sep { color: var(--t3); font-size: 13px }
/* 自定义区间展开/收起过渡（淡入+轻上移，展开方向与按钮行一致） */
.dpb-enter-active, .dpb-leave-active { transition: opacity 0.18s ease, transform 0.18s ease }
.dpb-enter-from, .dpb-leave-to { opacity: 0; transform: translateY(-3px) }
</style>
