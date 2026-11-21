<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api/client'

const props = defineProps({ taskId: { type: Number, required: true } })
const emit = defineEmits(['cancel', 'confirm'])
const preview = ref(null)
const error = ref('')
onMounted(async () => {
  try { preview.value = await api.aiContext(props.taskId) }
  catch (e) { error.value = e.message }
})
</script>

<template>
  <section class="preview" aria-labelledby="ai-preview-title">
    <h3 id="ai-preview-title">发送前检查分析摘要</h3>
    <p>以下摘要将发送到配置的模型服务。文件名、设备 ID、协商地址和诊断自由文本已隐藏，但端口、SSRC 等仍保留。追问及对话内容不会自动脱敏，发送前请自行检查。</p>
    <p v-if="error" role="alert">摘要加载失败：{{ error }}</p>
    <p v-else-if="!preview" role="status">正在读取摘要…</p>
    <pre v-else tabindex="0">{{ preview.context }}</pre>
    <div class="actions">
      <button type="button" class="btn" @click="emit('cancel')">取消</button>
      <button type="button" class="btn primary" :disabled="!preview" @click="emit('confirm', preview.context_hash)">发送并分析</button>
    </div>
  </section>
</template>

<style scoped>
.preview { margin: 16px; padding: 16px; border: 1px solid var(--line-strong); border-radius: var(--radius); background: var(--surface-2); }
h3 { font-size: 15px; margin: 0 0 8px; }
p { color: var(--text-2); line-height: 1.6; margin: 8px 0; }
pre { max-height: 240px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; color: var(--text); background: var(--bg); border: 1px solid var(--line); border-radius: var(--radius-sm); font: 12px/1.6 var(--font-mono); }
.actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.actions .btn.primary { background: var(--ds-dk); border-color: var(--ds-dk); color: #fff; }
.actions .btn.primary:hover:not(:disabled) { background: var(--ds); border-color: var(--ds); }
</style>
