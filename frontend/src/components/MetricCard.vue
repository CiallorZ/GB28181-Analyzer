<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  icon: { type: String, default: '' },
  tone: { type: String, default: '' },
  sub: { type: String, default: '' },
  samples: { type: Array, default: () => [] }
})

const path = computed(() => {
  if (props.samples.length < 2 || !props.samples.every(Number.isFinite)) return ''
  const low = Math.min(...props.samples)
  const high = Math.max(...props.samples)
  return props.samples.map((value, i) => {
    const x = 2 + 68 * i / (props.samples.length - 1)
    const y = high === low ? 13 : 24 - 22 * (value - low) / (high - low)
    return x + ',' + y
  }).join(' ')
})
</script>

<template>
  <article class="kpi" :class="tone">
    <div class="kpi-label">
      <span>{{ label }}</span><AppIcon v-if="icon" :name="icon" aria-hidden="true" />
    </div>
    <div class="kpi-value">
      {{ value == null ? '—' : (typeof value === 'number' ? value.toLocaleString() : value) }}
      <svg v-if="path" viewBox="0 0 72 26" aria-hidden="true">
        <polyline :points="path" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>
      </svg>
    </div>
    <div v-if="sub" class="kpi-sub">{{ sub }}</div>
  </article>
</template>

<style scoped>
/* Canonical .kpi grammar comes from theme.css; only the sparkline needs local styling. */
.kpi-label { width:100%; justify-content:space-between; }
.kpi-label .app-icon { width:16px; height:16px; flex:none; color:var(--text-3); }
.kpi-value { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.kpi-value svg { width:clamp(28px,4vw,72px); height:26px; color:var(--chart-primary); flex-shrink:1; min-width:0; }
</style>
