<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  icon: { type: String, required: true },
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
  <article class="metric-card">
    <header><span>{{ label }}</span><AppIcon :name="icon" aria-hidden="true" /></header>
    <div class="reading">
      <strong>{{ value == null ? '—' : value.toLocaleString() }}</strong>
      <svg v-if="path" viewBox="0 0 72 26" aria-hidden="true">
        <polyline :points="path" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round"/>
      </svg>
    </div>
  </article>
</template>

<style scoped>
.metric-card { min-width:0; display:grid; align-content:space-between; gap:12px; padding:13px 15px; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface); }
.metric-card header,.reading { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.metric-card header { color:var(--text-3); font-size:12px; font-weight:550; }
.metric-card header svg { width:16px; height:16px; flex:none; color:var(--text-3); }
.reading strong { font:650 clamp(21px,2vw,29px)/1.15 var(--font-heading); color:var(--text); font-variant-numeric:tabular-nums; letter-spacing:-.04em; }
.reading svg { width:clamp(28px,4vw,72px); height:26px; color:var(--chart-primary); flex-shrink:1; min-width:0; }
</style>
