<script setup>
defineProps({ stages: { type: Array, required: true } })
const emit = defineEmits(['navigate'])
</script>

<template>
  <section class="flow-map" aria-labelledby="flow-title">
    <header class="flow-head"><div><span class="flow-mark"></span><div><p>抓包分析</p><h2 id="flow-title">从信令<br>到画面</h2></div></div><p>仅反映当前抓包结果，<br>不代表端到端状态。</p></header>
    <ol class="flow-stages">
      <li v-for="(stage, index) in stages" :key="stage.key" :class="stage.tone">
        <button type="button" :disabled="!stage.available" @click="emit('navigate', stage.key)">
          <span class="stage-top"><span class="stage-index">0{{ index + 1 }}</span><span class="stage-dot"></span></span>
          <span class="stage-label">{{ stage.label }}</span><strong>{{ stage.value }}</strong><span class="stage-detail">{{ stage.detail }}</span>
          <span v-if="stage.available" class="stage-action">查看详情 <span aria-hidden="true">↗</span></span>
        </button>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.flow-map { display:grid; grid-template-columns:220px minmax(0,1fr); margin-bottom:20px; overflow:hidden; border:1px solid var(--line-2); border-radius:8px; background:var(--surface); }
.flow-head { position:relative; overflow:hidden; min-height:220px; padding:25px 24px; display:flex; flex-direction:column; justify-content:space-between; gap:20px; color:var(--text); background:var(--surface-2); border-right:1px solid var(--line); }
.flow-head::after { content:''; position:absolute; width:150px; height:150px; border:1px solid var(--brand-line); border-radius:50%; right:-65px; bottom:-50px; box-shadow:0 0 0 24px var(--brand-soft),0 0 0 48px var(--brand-soft); opacity:.55; pointer-events:none; }
.flow-head > div { display:flex; align-items:start; gap:10px; }.flow-mark { width:3px; height:38px; border-radius:2px; background:var(--brand); margin-top:4px; }.flow-head h2 { font-size:25px; line-height:1.2; letter-spacing:-.04em; }.flow-head div p { color:var(--brand-lt); font-size:11px; font-weight:650; margin-bottom:8px; }.flow-head > p { color:var(--text-3); font-size:11px; line-height:1.6; }
.flow-stages { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); list-style:none; }.flow-stages li { min-width:0; border-right:1px solid var(--line); }.flow-stages li:last-child { border-right:0; }
.flow-stages button { display:flex; flex-direction:column; align-items:start; width:100%; height:100%; padding:20px 22px; border:0; color:var(--text); background:transparent; text-align:left; font:inherit; cursor:pointer; transition:background .2s; }.flow-stages button:not(:disabled):hover { background:var(--brand-soft); }.flow-stages button:disabled { cursor:default; }
.stage-top { display:flex; align-items:center; width:100%; gap:12px; }.stage-index { font:11px var(--font-mono); color:var(--text-3); }.stage-top::after { content:''; flex:1; height:1px; background:var(--line-2); }.stage-dot { width:7px; height:7px; flex:none; border-radius:50%; background:var(--brand); box-shadow:0 0 0 4px var(--brand-soft); }.warning .stage-dot { background:var(--warning); box-shadow:0 0 0 4px var(--warning-soft); }.critical .stage-dot { background:var(--critical); box-shadow:0 0 0 4px var(--critical-soft); }
.stage-label { margin-top:18px; color:var(--text-3); font-size:12px; }.flow-stages strong { margin-top:4px; font-size:clamp(18px,1.5vw,23px); line-height:1.3; }.stage-detail { margin-top:4px; color:var(--text-3); font-size:11.5px; }.stage-action { margin-top:15px; color:var(--brand-lt); font-size:11px; font-weight:650; }
@media (max-width:1000px) { .flow-map { grid-template-columns:1fr; }.flow-head { min-height:0; flex-direction:row; align-items:end; padding:18px 20px; border-right:0; border-bottom:1px solid var(--line); }.flow-head h2 { font-size:20px; }.flow-head h2 br,.flow-head > p br { display:none; }.flow-mark { height:30px; }.flow-head > p { text-align:right; } }
@media (max-width:700px) { .flow-head { align-items:start; flex-direction:column; gap:8px; }.flow-head > p { text-align:left; margin-left:13px; }.flow-stages { grid-template-columns:repeat(2,minmax(0,1fr)); }.flow-stages li:nth-child(2) { border-right:0; }.flow-stages li:nth-child(n+3) { border-top:1px solid var(--line); }.flow-stages button { padding:16px; } }
@media (prefers-reduced-motion:reduce) { .flow-stages button { transition:none; } }
</style>
