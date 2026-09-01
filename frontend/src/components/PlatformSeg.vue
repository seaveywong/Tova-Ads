<script setup>
// 平台分段切换器（全部/Facebook/TikTok，连接式三段）。
// 直连 usePlatform 全局单例：点选即写全局（localStorage 持久），各页 watch(platform) 联动过滤；
// 同时暴露 v-model:model-value + update 事件，便于父组件显式绑定。
// size: default(28px) / small(24px)；移动端保留文字（不隐藏）。
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePlatform } from '../composables/usePlatform'

const props = defineProps({
  modelValue: { type: String, default: 'all' },
  size: { type: String, default: 'default' },
})
const emit = defineEmits(['update:modelValue'])
const { platform, setPlatform } = usePlatform()
const { t } = useI18n()

const opts = computed(() => [
  { v: 'all', label: t('common.all') },
  { v: 'fb', label: 'Facebook' },
  { v: 'tt', label: 'TikTok' },
])
const pick = (v) => {
  if (v === platform.value) return
  setPlatform(v)
  emit('update:modelValue', v)
}
</script>

<template>
  <div class="pseg" :class="size" role="group" :aria-label="t('common.all')">
    <button v-for="o in opts" :key="o.v" type="button" class="pseg-btn"
            :class="{ on: platform === o.v }" @click="pick(o.v)">
      <span class="pseg-dot" :class="o.v"></span>
      <span class="pseg-txt">{{ o.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.pseg { display: inline-flex; align-items: stretch; flex-shrink: 0 }
.pseg-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 0 12px; height: 30px;
  background: var(--bg2); color: var(--t2);
  border: 1px solid var(--bd);
  font-size: 13px; cursor: pointer; font-family: inherit;
  transition: all 0.15s; white-space: nowrap;
}
.pseg.small .pseg-btn { height: 26px; padding: 0 10px; font-size: 12px }
.pseg-btn + .pseg-btn { margin-left: -1px }
.pseg-btn:first-child { border-radius: var(--rs) 0 0 var(--rs) }
.pseg-btn:last-child { border-radius: 0 var(--rs) var(--rs) 0 }
.pseg-btn:hover { color: var(--t1); border-color: var(--bd2); z-index: 1; position: relative }
.pseg-btn.on { background: var(--acg); color: var(--ac); border-color: var(--ac); position: relative; z-index: 1 }
/* 品牌点：all=中性灰点、FB=品牌蓝、TT=青粉渐变 */
.pseg-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: var(--t3) }
.pseg-dot.fb { background: #1877f2 }
.pseg-dot.tt { background: linear-gradient(135deg, #25f4ee 45%, #fe2c55 55%) }
.pseg-txt { line-height: 1 }
</style>
