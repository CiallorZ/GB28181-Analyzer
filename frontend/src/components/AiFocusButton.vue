<script setup>
import { useTaskStore } from '../stores/task'
defineProps({
  focus: { type: String, required: true },
  label: { type: String, required: true }
})
const store = useTaskStore()
</script>

<template>
  <button v-if="store.task?.status === 'completed'" type="button" class="ai-focus"
          data-cue="confirm" @click="store.openAiPanel(focus)">
    <img src="/brand/deepseek.svg" alt="" width="18" height="18">
    <span>{{ label }}</span>
  </button>
</template>

<style scoped>
.ai-focus {
  display:inline-flex; align-items:center; gap:8px; min-height:34px; padding:4px 12px;
  border:1px solid var(--ds-line); border-radius:var(--radius-sm); background:var(--ds-soft);
  color:var(--ds-lt); font:inherit; font-size:13px; font-weight:600; cursor:pointer;
}
.ai-focus:hover { border-color:var(--ds-lt); }
.ai-focus img { object-fit:contain; }
</style>
