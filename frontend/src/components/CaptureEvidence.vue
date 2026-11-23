<script setup>
import { ref, computed } from 'vue'
const props = defineProps({taskId:Number, streams:Array})
const tab = ref(''), rows = ref([]), error = ref(''), busy = ref(false)
const selectedSsrc = ref('')
const lossOnly = ref(false)
const sources = computed(() => [...new Set(rows.value.map(row => row.ssrc))])
const visibleReports = computed(() => rows.value.filter(row =>
  (!selectedSsrc.value || row.ssrc === selectedSsrc.value) && (!lossOnly.value || row.loss > 0)))
let request = 0
async function show(value) {
  const seq = ++request
  selectedSsrc.value = ''
  lossOnly.value = false
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
<div v-else-if="tab==='rtcp'" class="scroll"><div class="filters"><label>报告对象 <select v-model="selectedSsrc"><option value="">全部 SSRC</option><option v-for="s in sources" :key="s">{{s}}</option></select></label><label><input type="checkbox" v-model="lossOnly"> 仅区间丢包</label><span>{{visibleReports.length}} / {{rows.length}} 条</span></div><table><thead><tr><th>帧号</th><th>SSRC</th><th>区间丢包率</th><th>累计丢包</th><th>抖动（时钟单位）</th><th>帧 RTT（ms）</th></tr></thead><tbody><tr v-for="(r,i) in visibleReports" :key="i"><td><router-link :to="{path:'/packets',query:{task:taskId,number:r.frame}}">#{{r.frame}}</router-link></td><td>{{r.ssrc}}</td><td>{{r.loss}}%</td><td>{{r.lost}}</td><td>{{r.jitter}}</td><td>{{r.delay ?? '—'}}</td></tr></tbody></table><p v-if="!visibleReports.length">没有符合筛选条件的接收报告。</p></div>
<div class="options"><a v-for="s in streams" :key="s.id" class="btn" :href="'/api/v1/streams/'+s.id+'/capture'" download>导出 {{s.transport.toUpperCase()==='TCP'?'TCP 单向连接':'RTP 流'}} #{{s.id}}</a></div>
</details></template>
<style scoped>.evidence{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}.evidence summary{cursor:pointer;font-weight:650}.options{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.edge{display:flex;align-items:center;gap:14px;padding:8px;border-bottom:1px solid var(--line);overflow-wrap:anywhere}.edge span{color:var(--brand-lt);font:12px var(--font-mono)}.scroll{overflow:auto;max-height:420px}.filters{display:flex;align-items:center;flex-wrap:wrap;gap:12px;padding:10px;background:var(--surface-2);color:var(--text-2)}.filters select{background:var(--surface);color:var(--text);border:1px solid var(--line-2);border-radius:4px;padding:4px}</style>