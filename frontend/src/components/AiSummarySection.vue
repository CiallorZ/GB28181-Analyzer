<script setup>
import { useTaskStore } from '../stores/task'
const store = useTaskStore()
</script>
<template><button class="consult" @click="store.openAiPanel()"><img src="/brand/deepseek.svg" alt=""><span><strong>DeepSeek 抓包会诊</strong><small>选择专家，结合本次抓包研判并追问</small></span><b>进入会诊 <AppIcon name="open" /></b></button></template>
<style scoped>
.consult {width:100%;display:flex;align-items:center;gap:16px;padding:22px;text-align:left;background:linear-gradient(110deg,var(--ds-soft),var(--surface) 55%,var(--brand-soft));border:1px solid var(--ds-line);border-radius:12px;color:var(--text);cursor:pointer}
.consult img {width:40px}.consult strong {font-size:17px}.consult small {display:block;color:var(--text-2);margin-top:5px}.consult b {margin-left:auto;color:var(--ds-lt)}
</style>
