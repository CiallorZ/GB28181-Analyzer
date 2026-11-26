<script setup>
/**
 * 发送前确认
 *
 * 会诊唯一一次把内容送出本机，所以这里必须让人看清"发了什么"：
 * 摘要原文、脱敏说明、本次视角，再给一个明确的发送动作。
 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client'

const props = defineProps({
  taskId: { type: Number, required: true },
  expert: { type: String, default: '综合研判' },
  connected: { type: Boolean, default: false },
  modelEndpoint: { type: String, default: '' }
})
const emit = defineEmits(['cancel', 'confirm', 'configure'])

const preview = ref(null)
const error = ref('')
const expanded = ref(false)

const recipient = computed(() => {
  try { return new URL(props.modelEndpoint).host }
  catch { return '' }
})
const lines = computed(() => (preview.value?.context || '').split('\n').length)
const truncated = computed(() => {
  const text = preview.value?.context || ''
  return !expanded.value && text.length > 1400
})
const shown = computed(() => {
  const text = preview.value?.context || ''
  return truncated.value ? text.slice(0, 1400) + '\n…' : text
})

onMounted(async () => {
  try { preview.value = await api.aiContext(props.taskId) }
  catch (e) { error.value = e.message }
})
</script>

<template>
  <section class="pv" aria-labelledby="ai-preview-title">
    <header class="pv-head">
      <h3 id="ai-preview-title">确认发送内容</h3>
      <p>以下任务摘要将发送给{{ recipient || '已配置的模型服务' }}，发送后才会生成报告。</p>
    </header>

    <div class="pv-scope">
      <div class="pv-scope-item">
        <span>会诊视角</span>
        <b>{{ expert }}</b>
      </div>
      <div class="pv-scope-item">
        <span>任务</span>
        <b>#{{ taskId }}</b>
      </div>
      <div class="pv-scope-item" v-if="preview">
        <span>摘要规模</span>
        <b>{{ preview.context.length.toLocaleString() }} 字 · {{ lines }} 行</b>
      </div>
    </div>

    <ul class="pv-mask" aria-label="脱敏范围">
      <li class="hide">已隐藏：文件名、设备 ID、协商地址、诊断自由文本</li>
      <li class="keep">仍保留：端口、SSRC、时间、计数与规则编号</li>
    </ul>

    <p v-if="error" class="pv-error" role="alert">摘要加载失败：{{ error }}</p>
    <p v-else-if="!preview" class="pv-loading" role="status">正在读取摘要…</p>

    <div v-else class="pv-code">
      <div class="pv-code-bar">
        <span class="mono">context.md</span>
        <button v-if="preview.context.length > 1400" type="button" class="pv-more" @click="expanded = !expanded">
          {{ expanded ? '收起' : '展开全文' }}
        </button>
      </div>
      <pre tabindex="0">{{ shown }}</pre>
    </div>

    <div class="pv-acts">
      <button type="button" class="btn" @click="emit('cancel')">返回</button>
      <button type="button" class="btn primary" :disabled="!preview" @click="connected ? emit('confirm', preview.context_hash) : emit('configure')">
        {{ connected ? '发送并分析' : '配置 DeepSeek 连接' }}
      </button>
      <span class="pv-note">追问内容不会自动脱敏，请勿粘贴敏感信息。</span>
    </div>
  </section>
</template>

<style scoped>
.pv { padding: 16px 18px 22px; max-width: 720px; }

.pv-head h3 {
  margin: 0;
  font-size: 13px; font-weight: 650; color: var(--text);
}
.pv-head p {
  margin: 4px 0 0;
  font-size: 11.5px; color: var(--text-4); line-height: 1.6;
}

.pv-scope {
  display: flex; flex-wrap: wrap;
  gap: 1px;
  margin: 14px 0 12px;
  background: var(--line);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.pv-scope-item {
  flex: 1 1 150px;
  padding: 8px 11px;
  background: var(--surface);
}
.pv-scope-item span { display: block; font-size: 10.5px; color: var(--text-4); }
.pv-scope-item b {
  display: block; margin-top: 3px;
  font-size: 12px; font-weight: 600; color: var(--text-2);
  font-family: var(--font-data);
}

.pv-mask {
  list-style: none; margin: 0 0 14px; padding: 0;
  display: flex; flex-direction: column; gap: 5px;
}
.pv-mask li {
  position: relative;
  padding-left: 16px;
  font-size: 11.5px; line-height: 1.55;
  color: var(--text-3);
}
.pv-mask li::before {
  content: '';
  position: absolute; left: 2px; top: 6px;
  width: 6px; height: 6px; border-radius: 50%;
}
.pv-mask li.hide::before { background: var(--ok); }
.pv-mask li.keep::before { background: var(--warning); }

.pv-error { margin: 0; font-size: 12px; color: var(--critical); }
.pv-loading { margin: 0; font-size: 12px; color: var(--text-4); }

.pv-code {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: var(--bg);
}
.pv-code-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  font-size: 11px; color: var(--text-4);
}
.pv-more {
  margin-left: auto;
  border: 0; background: transparent;
  color: var(--ds); font: inherit; font-size: 11px;
  cursor: pointer; padding: 0;
}
.pv-more:hover { text-decoration: underline; text-underline-offset: 2px; }
.pv-code pre {
  margin: 0;
  padding: 11px 12px;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-family: var(--font-mono);
  font-size: 11.5px; line-height: 1.62;
  color: var(--text-2);
}

.pv-acts {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  margin-top: 14px;
}
.pv-note { font-size: 11px; color: var(--text-4); }


.pv-acts .btn.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.pv-acts .btn.primary:hover:not(:disabled) {
  background: var(--brand-hover);
  border-color: var(--brand-hover);
}

@media (max-width: 620px) {
  .pv { padding-inline: 14px; }
  .pv-note { flex-basis: 100%; }
}
</style>

