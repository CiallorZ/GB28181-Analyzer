<script setup>
import { ref } from 'vue'
const props = defineProps({taskId:Number, streams:Array})
const tab = ref(''), rows = ref([]), error = ref(''), busy = ref(false)
let request = 0
async function show(value) {
  const seq = ++request
  tab.value = value
  rows.value = []
  error.value = ''
  busy.value = true
  try {
    const response = await fetch('/api/v1/tasks/'+props.taskId+'/'+value)
    const data = await response.json()
    if (!response.ok) throw Error(data.detail || '读取失败')
    if (seq === request) rows.value = data
  } catch(e) { if(seq === request) error.value = e.message }
  finally { if(seq === request) busy.value = false }
}
</script>
<template><details class="evidence"><summary>设备拓扑与媒体证据</summary>
<div class="options"><button class="btn" @click="show('topology')">设备拓扑</button><button class="btn" @click="show('rtcp')">RTCP 接收报告</button></div>
<p v-if="busy" role="status">正在读取证据…</p><p v-else-if="error" role="alert">{{ error }}</p>
<p v-else-if="tab && !rows.length">此抓包未观察到{{ tab==='rtcp'?'可识别的 RTCP 接收报告块':'设备关联' }}。</p>
<template v-else-if="tab==='topology'"><div v-for="edge in rows" :key="[edge.source,edge.target,edge.label].join('|')" class="edge"><strong>{{edge.source || '未知端点'}}</strong><span>{{edge.label}} {{edge.count ?? ''}} →</span><strong>{{edge.target || '未知端点'}}</strong></div></template>
<div v-else-if="tab==='rtcp'" class="scroll"><table><thead><tr><th>帧号</th><th>SSRC</th><th>区间丢包率</th><th>累计丢包</th><th>抖动（时钟单位）</th><th>帧 RTT（ms）</th></tr></thead><tbody><tr v-for="(r,i) in rows" :key="i"><td>{{r.frame}}</td><td>{{r.ssrc}}</td><td>{{r.loss}}%</td><td>{{r.lost}}</td><td>{{r.jitter}}</td><td>{{r.delay ?? '—'}}</td></tr></tbody></table></div>
<div class="options"><a v-for="s in streams" :key="s.id" class="btn" :href="'/api/v1/streams/'+s.id+'/capture'" download>导出 {{s.transport.toUpperCase()==='TCP'?'TCP 单向连接':'RTP 流'}} #{{s.id}}</a></div>
</details></template>
<style scoped>.evidence{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}.evidence summary{cursor:pointer;font-weight:650}.options{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.edge{display:flex;align-items:center;gap:14px;padding:8px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.edge span{color:var(--brand-lt);font:12px var(--font-mono)}.scroll{overflow:auto;max-height:420px}</style>