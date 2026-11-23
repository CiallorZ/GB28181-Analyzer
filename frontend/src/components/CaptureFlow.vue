<script setup>
defineProps({ stages: { type: Array, required: true }, filename: String, hasSessions: Boolean })
const emit = defineEmits(['navigate'])
</script>

<template>
  <section class="flow-map glass-panel" aria-labelledby="flow-title">
    <header class="flow-head">
      <div class="flow-identity">
        <span class="source"><img src="/brand/analyzer.svg" alt="" width="22" height="22">抓包证据链</span>
        <h2 id="flow-title">{{ filename }}</h2>
      </div>
      <router-link v-if="hasSessions" class="signal-link" to="/sip">查看信令交互 <span aria-hidden="true"><AppIcon name="open" /></span></router-link>
    </header>
    <ol class="flow-stages">
      <li v-for="stage in stages" :key="stage.key" :class="stage.tone">
        <button type="button" :disabled="!stage.available" @click="emit('navigate', stage.key)">
          <span class="stage-top"><span class="stage-index"><AppIcon :name="stage.icon" /></span><span class="rail" aria-hidden="true"></span></span>
          <span class="stage-label">{{ stage.label }}</span><strong>{{ stage.value }}</strong><span class="stage-detail">{{ stage.detail }}</span>
          <span v-if="stage.available" class="stage-action">查看{{ stage.label }}详情 <span aria-hidden="true"><AppIcon name="open" /></span></span>
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.flow-map { margin-bottom:20px; padding:clamp(16px,2.5vw,32px); border:1px solid var(--line-2); border-radius:12px; background:linear-gradient(110deg,var(--surface),var(--surface-2)); }
.flow-head { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:6px 16px; margin-bottom:20px; }
.flow-identity { min-width:0; }
.source { display:flex; align-items:center; gap:8px; color:var(--brand-lt); font-weight:600; font-size:12px; }
.signal-link { color:var(--brand-lt); border:1px solid var(--line-2); background:var(--surface); padding:8px 14px; border-radius:6px; font-weight:600; text-decoration:none; }
.signal-link:hover { border-color:var(--brand-lt); }
.flow-head h2 { margin-top:6px; overflow-wrap:anywhere; font-size:clamp(20px,3vw,36px); letter-spacing:-.035em; }
.flow-head p,.stage-detail { color:var(--text-3); font-size:12px; }
.flow-stages { padding-top:16px; border-top:1px solid var(--line-2); display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); list-style:none; }
.flow-stages li { min-width:0; }
.flow-stages button { width:100%; height:100%; display:flex; flex-direction:column; align-items:start; padding:2px 0; text-align:left; font:inherit; background:transparent; border:0; color:var(--text); cursor:pointer; }
.flow-stages button:disabled { cursor:default; }
.stage-top { display:flex; align-items:center; width:100%; }
.stage-index { display:grid; place-items:center; width:32px; height:32px; border:1px solid var(--line-strong); border-radius:9px; background:var(--surface); color:var(--brand-lt); font-size:17px; }
.warning .stage-index { color:var(--warning); border-color:currentColor; }
.critical .stage-index { color:var(--critical); border-color:currentColor; }
.rail { height:1px; background:var(--line-2); flex:1; margin-inline:6px; transform-origin:left; }
li:last-child .rail { visibility:hidden; }
button:is(:hover,:focus-visible):enabled .rail { background:var(--brand-lt); animation:draw .35s ease-out; }
@keyframes draw { from { transform:scaleX(0); } }
.stage-label { color:var(--text-2); margin-top:12px; font-size:13px; }
.flow-stages strong { margin:3px 0; font-size:clamp(19px,1.9vw,28px); font-variant-numeric:tabular-nums; }
.stage-detail { padding-right:12px; }
.stage-action { margin-top:auto; padding-top:12px; color:var(--brand-lt); font-size:12px; }
@media(max-width:680px) {
  .flow-stages { grid-template-columns:1fr; }
  .flow-stages button { position:relative; padding:0 0 16px 40px; }
  .stage-top { position:absolute; inset:0 auto 0 0; width:32px; flex-direction:column; }
  .stage-index { flex:none; }
  .rail { width:1px; margin:4px 0; }
  .stage-label { margin:0; }
  .stage-action { padding-top:4px; }
}
@media(prefers-reduced-motion:reduce) { button:is(:hover,:focus-visible):enabled .rail { animation:none; } }
</style>
