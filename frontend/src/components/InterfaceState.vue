<script setup>
defineProps({
  kind: { type: String, default: 'empty' },
  title: { type: String, required: true },
  detail: { type: String, default: '' },
  icon: { type: String, default: 'file' }
})
</script>

<template>
  <div class="interface-state" :class="kind" :role="kind === 'error' ? 'alert' : 'status'">
    <div v-if="kind === 'loading'" class="state-skeleton" aria-hidden="true">
      <i v-for="row in 3" :key="row"></i>
    </div>
    <span v-else class="state-icon"><AppIcon :name="kind === 'error' ? 'warning' : icon" /></span>
    <div class="state-text">
      <strong>{{ title }}</strong>
      <p v-if="detail">{{ detail }}</p>
    </div>
    <div v-if="$slots.default" class="state-action"><slot /></div>
  </div>
</template>

<style scoped>
.interface-state {
  display:grid;
  justify-items:center;
  gap:11px;
  padding:clamp(18px,3vw,32px) 16px;
  text-align:center;
}
.state-icon {
  display:grid; place-items:center;
  inline-size:42px; block-size:42px;
  border:1px solid var(--line);
  border-radius:var(--radius);
  background:var(--ui-layer-raised);
  color:var(--info);
  font-size:19px;
}
.error .state-icon { color:var(--critical); background:var(--critical-soft); }
.state-text { min-width:0; max-width:46ch; overflow-wrap:anywhere; }
.state-text strong { font-family:var(--font-heading); font-size:14px; color:var(--text); }
.state-text p { margin:4px 0 0; color:var(--text-3); font-size:12px; }
.state-action { display:flex; flex-wrap:wrap; justify-content:center; gap:7px; }
.state-skeleton { display:grid; gap:7px; width:min(280px,85%); }
.state-skeleton i {
  height:8px;
  border-radius:8px;
  background:var(--surface-3);
  animation:state-pulse 1.4s ease-in-out infinite alternate;
}
.state-skeleton i:nth-child(2) { width:80%; animation-delay:100ms; }
.state-skeleton i:nth-child(3) { width:57%; animation-delay:200ms; }
@keyframes state-pulse { from { opacity:.5; } to { opacity:1; } }
</style>
