<script setup>
import { RadioGroupItem, RadioGroupRoot } from 'reka-ui'

defineProps({ profiles: { type: Object, required: true } })
const expert = defineModel({ type: String, required: true })
const icons = { general: 'compare', sip: 'signal', media: 'wave', field: 'settings' }
</script>

<template>
  <RadioGroupRoot v-model="expert" orientation="vertical" aria-label="会诊视角" class="specialists">
    <RadioGroupItem v-for="(profile, key) in profiles" :key="key" :value="key" class="specialist"
                    @keyup.up="expert = key" @keyup.down="expert = key">
      <span class="glyph"><AppIcon :name="icons[key]" /></span>
      <span><strong>{{ profile[0] }}</strong><small>{{ profile[1] }}</small></span>
    </RadioGroupItem>
  </RadioGroupRoot>
</template>

<style scoped>
.specialists { display:grid; gap:6px; }
.specialist { display:flex; align-items:center; gap:10px; width:100%; padding:12px 10px; border:1px solid transparent; border-radius:var(--radius-sm); background:transparent; color:var(--text); text-align:left; font:inherit; cursor:pointer; transition:background-color var(--dur),border-color var(--dur); }
.specialist:hover { background:var(--surface-2); }
.specialist[data-state=checked] { background:var(--bg-selected); border-color:color-mix(in srgb,var(--brand) 28%,var(--line)); }
.glyph { display:grid; place-items:center; flex:none; width:30px; height:30px; background:var(--surface-2); border:1px solid var(--line); border-radius:8px; color:var(--text-2); }
.glyph svg { width:16px; height:16px; }
[data-state=checked] .glyph { background:var(--brand); color:white; border-color:transparent; }
strong,small { display:block; } strong { font-size:13px; } small { font-size:11px; line-height:1.5; margin-top:3px; color:var(--text-3); }
.specialist:focus-visible { outline:2px solid var(--focus-ring); outline-offset:1px; }
</style>

