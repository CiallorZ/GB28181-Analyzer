<script setup>
import { computed, ref, watch, shallowRef } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { api } from '../api/client'
import { groups,judgments,fieldName,formatValue,allowedLink } from '../utils/compare'
const route=useRoute(), router=useRouter()
const data=shallowRef(null), error=ref(''), loading=ref(false), onlyDiff=ref(false), tab=ref(0), page=ref(1)
const visible=computed(() => {
  if(!data.value) return []
  const [,layer,accept]=groups[tab.value]
  return data.value.result[layer].map(row => ({...row, cells:Object.entries(row.fields).filter(([k,v])=>accept(k)&&(!onlyDiff.value || v[2]!=='same'))})).filter(row=>row.cells.length)
})
watch([tab,onlyDiff],()=>{page.value=1})
watch(()=>route.params.id,async(id,_,cleanup)=>{
  let active=true
  cleanup(()=>{active=false})
  loading.value=true; error.value='';data.value=null;page.value=1
  try {const value=await api.comparison(id);if(active)data.value=value}
  catch(e){if(active)error.value=e.message}
  finally{if(active)loading.value=false}
},{immediate:true})
async function jump(side,session=null) {
  try {
    const fresh=await api.comparison(data.value.id)
    data.value=fresh
    if(allowedLink(fresh,side,session)) await router.push(session==null?{path:'/packets',query:{task:fresh['task_'+side+'_id']}}:'/sessions/'+session)
  } catch(e){error.value=e.message}
}
function reason(side,id) {return data.value.stale?'快照已过期':allowedLink(data.value,side,id)?'':'目标记录不可用'}
</script>
<template><main class="page"><router-link to="/compare">返回双抓包对比</router-link><h1>对比快照 #{{route.params.id}}</h1>
<p v-if="loading" role="status">正在读取快照…</p><p v-if="error" class="err-box" role="alert">{{error}}</p>
<template v-if="data"><div v-if="data.stale" class="err-box">输入任务已变化。当前显示已保存的快照，原始证据跳转已禁用。</div>
<div class="grid-2"><div v-for="side in ['a','b']" :key="side" class="card card-body"><h2>{{side.toUpperCase()}} · {{data['label_'+side] || '抓包'}} #{{data['task_'+side+'_id']}}</h2>
<p v-for="f in data.fingerprint[side].files" :key="f.filename">{{f.filename}}</p><small>完成时间（UTC） {{formatValue(data.fingerprint[side].completed_at)}}</small><p><button class="btn" :disabled="!!reason(side,null)" @click="jump(side)">查看报文</button> {{reason(side,null)}}</p></div></div>
<p>{{data.result.methods}}</p><p>已对齐 {{data.summary.aligned_sessions}} 个会话、{{data.summary.aligned_streams}} 条流。结构或精确值差异 {{data.summary.structural}} 项，超出对比容差 {{data.summary.beyond_tolerance}} 项，无法比较 {{data.summary.unknown}} 项。</p>
<div class="tools"><label><input type="checkbox" v-model="onlyDiff"> 只看差异（含未知）</label><a v-for="fmt in ['md','json']" :key="fmt" class="btn" download :href="'/api/v1/comparisons/'+data.id+'/report?format='+fmt">导出 .{{fmt}}</a></div>
<p v-if="data.result.truncated">明细已截断，汇总按完整输入计算。完整记录数：会话 {{data.result.totals.sessions}}、流 {{data.result.totals.streams}}、规则 {{data.result.totals.diagnostics}}。</p>
<div class="tools"><button v-for="([name],i) in groups" :key="name" class="btn" :aria-pressed="tab===i" @click="tab=i">{{name}}</button></div>
<p v-if="!visible.length">当前分区没有符合条件的记录。</p>
<article class="card card-body" v-for="r in visible.slice((page-1)*10,page*10)" :key="r.rule_id || r.a">
<h3>{{r.rule_id || ('A #'+r.a+' / B #'+r.b)}}　<span :class="{'text-warning':r.confidence==='low'}">{{r.confidence==='low'?'低置信度推断':r.method?'精确对齐':'规则编号对齐'}}</span></h3>
<div v-if="r.method" class="tools"><span v-for="side in ['a','b']" :key="side"><button class="btn xs" :disabled="!!reason(side,r['session_'+side])" @click="jump(side,r['session_'+side])">{{side.toUpperCase()}} 侧会话</button> {{reason(side,r['session_'+side])}}</span></div>
<div class="scroll"><table class="tbl"><thead><tr><th>字段</th><th>A 侧</th><th>B 侧</th><th>判定</th></tr></thead><tbody><tr v-for="[k,[a,b,status]] in r.cells" :key="k"><td>{{fieldName(k)}}</td><td>{{formatValue(a)}}</td><td>{{formatValue(b)}}</td><td><span class="badge" :class="status==='different'?'warning':'unknown'">{{status==='different' && k in data.result.tolerances?'超出对比容差':judgments[status]}}</span></td></tr></tbody></table></div></article>
<div v-if="visible.length>10" class="tools"><button class="btn" :disabled="page===1" @click="page--">上一页</button>{{page}} / {{Math.ceil(visible.length/10)}}<button class="btn" :disabled="page*10>=visible.length" @click="page++">下一页</button></div>
<details class="card card-body"><summary>未对齐项 · {{data.summary.unaligned}} 条（不计入差异汇总）</summary><p v-if="!data.summary.unaligned">没有未对齐记录。</p><p v-for="r in data.result.unmatched" :key="[r.layer,r.side,r.id].join('-')">{{({sessions:'会话',streams:'媒体流',diagnostics:'诊断事件'})[r.layer]}} · {{r.side.toUpperCase()}} #{{r.id}}　{{judgments[r.status]}}</p></details>
<p v-for="note in data.result.limitations" :key="note">{{note}}</p></template></main></template>
<style scoped>.page>p,.page>article,.page>details,.tools{margin:12px 0}.tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.tools [aria-pressed=true]{border-color:var(--brand);color:var(--brand-lt)}.scroll{overflow:auto}th,td{text-align:left}h3{font-size:14px}.card{overflow-wrap:anywhere}summary{cursor:pointer}</style>
