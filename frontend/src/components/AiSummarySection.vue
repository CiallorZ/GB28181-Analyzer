<script setup>
/**
 * AI 会诊入口
 *
 * 放在分析结果末尾，承担"从这里进入会诊"的唯一职责：
 * 先给出本次研判依据的关键数字，再给一个明确的主操作。
 */
import { computed } from 'vue'
import { useTaskStore } from '../stores/task'

const store = useTaskStore()

const facts = computed(() => {
  const s = store.task?.summary || {}
  const d = s.diagnostics || {}
  const rate = s.signal_success_rate
  return [
    { k: '报文', v: (s.packet_count || 0).toLocaleString() },
    { k: '会话', v: s.session_count ?? 0 },
    { k: '信令成功', v: rate != null ? rate.toFixed(0) + '%' : '—' },
    { k: '诊断', v: (d.critical || 0) + (d.warning || 0) + (d.info || 0) }
  ]
})
</script>

<template>
  <section class="ai-entry" aria-labelledby="ai-entry-title">
    <div class="ae-main">
      <span class="ae-mark" aria-hidden="true"><img src="/brand/deepseek.svg" alt="" /></span>
      <div class="ae-copy">
        <h2 id="ai-entry-title">DeepSeek 会诊</h2>
        <p>把本次信令、媒体与规则结论交给模型，得到一份可追问的排查意见。</p>
      </div>
    </div>

    <dl class="ae-facts" aria-label="本次研判依据">
      <div v-for="f in facts" :key="f.k">
        <dt>{{ f.k }}</dt>
        <dd>{{ f.v }}</dd>
      </div>
    </dl>

    <button type="button" class="ae-action" @click="store.openAiPanel()">
      开始会诊<span aria-hidden="true"><AppIcon name="forward" /></span>
    </button>
  </section>
</template>

<style scoped>
.ai-entry {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'main action'
    'facts action';
  align-items: center;
  gap: 12px 20px;
  padding: 16px 18px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 3px solid var(--ds);
  border-radius: var(--radius);
}

.ae-main { grid-area: main; display: flex; align-items: center; gap: 12px; min-width: 0; }
.ae-mark {
  flex: none;
  display: grid; place-items: center;
  width: 34px; height: 34px;
  border-radius: var(--radius-sm);
  background: var(--ds-soft);
  border: 1px solid var(--ds-line);
}
.ae-mark img { width: 19px; height: auto; }
.ae-copy { min-width: 0; }
.ae-copy h2 {
  margin: 0;
  font-size: 14px; font-weight: 650;
  color: var(--text); letter-spacing: .01em;
}
.ae-copy p {
  margin: 3px 0 0;
  font-size: 12px; line-height: 1.55;
  color: var(--text-3);
}

.ae-facts {
  grid-area: facts;
  display: flex; flex-wrap: wrap;
  gap: 4px 18px;
  margin: 0;
}
.ae-facts div { display: flex; align-items: baseline; gap: 6px; }
.ae-facts dt { font-size: 11px; color: var(--text-4); }
.ae-facts dd {
  margin: 0;
  font-size: 12.5px; font-weight: 600;
  color: var(--text-2);
  font-family: var(--font-data);
  font-variant-numeric: tabular-nums;
}

.ae-action {
  grid-area: action;
  display: inline-flex; align-items: center; gap: 6px;
  height: 34px; padding: 0 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--ds-dk);
  background: var(--ds-dk);
  color: #fff;
  font: inherit; font-size: 12.5px; font-weight: 550;
  cursor: pointer;
  transition: background-color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.ae-action:hover { background: var(--ds); border-color: var(--ds); }
.ae-action :deep(svg) { width: 13px; height: 13px; }
.ae-action:focus-visible { outline: 2px solid var(--ds); outline-offset: 2px; }

@media (max-width: 720px) {
  .ai-entry {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'main' 'facts' 'action';
    gap: 12px;
  }
  .ae-action { width: 100%; justify-content: center; }
}
</style>

