<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import PaneDivider from '../components/PaneDivider.vue'
import PageNav from '../components/PageNav.vue'
import { useTaskStore } from '../stores/task'

const listHeight = ref(300)
const props=defineProps({embedded:Boolean,seed:Array,seedTotal:Number,range:Array})
const listLoading=ref(false), descending=ref(false)
const route = useRoute()
const store = useTaskStore()

const items = ref(props.seed || [])
const linkedPacket = ref(null)
const visiblePackets = computed(() => linkedPacket.value ? [linkedPacket.value, ...items.value] : items.value)
const total = ref(props.seedTotal || 0)
const page = ref(1)
const pageSize = props.embedded ? 8 : 200
const ipFilter = ref('')
const portFilter = ref('')
const protoFilter = ref('')
const callIdFilter = ref('')
const err = ref('')

const selectedId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)


let listSeq = 0
async function load() {
  if (!store.currentTaskId) return
  const taskId = store.currentTaskId
  const seq = ++listSeq
  listLoading.value = true
  linkedPacket.value = null
  err.value = ''
  detailSeq++
  packetLookup++
  selectedId.value = null
  detail.value = null
  detailLoading.value = false
  try {
    const r = await api.packets(taskId, {
      page: page.value, page_size: pageSize,
      time_from:props.range?.[0], time_to:props.range?.[1], descending:descending.value,
      ip: ipFilter.value || undefined,
      port: portFilter.value ? Number(portFilter.value) : undefined,
      protocol: protoFilter.value || undefined,
      call_id: callIdFilter.value || undefined
    })
    if (seq === listSeq && taskId === store.currentTaskId) {
      items.value = r.items
      total.value = r.total
    }
  } catch (e) {
    if (seq === listSeq) {
      err.value = e.message
      items.value = []
      total.value = 0
    }
  } finally {
    if (seq === listSeq) listLoading.value = false
  }
}

let detailSeq = 0
async function openPacket(p) {
  const seq = ++detailSeq
  const taskId = store.currentTaskId
  packetLookup++
  if (linkedPacket.value?.id !== p.id) linkedPacket.value = null
  selectedId.value = p.id
  detail.value = null
  err.value = ''
  detailLoading.value = true
  try {
    const result = await api.packet(p.id)
    if (seq === detailSeq && taskId === store.currentTaskId) detail.value = result
  } catch (e) { if (seq === detailSeq) err.value = e.message }
  finally { if (seq === detailSeq) detailLoading.value = false }
}

const highlightedField = ref(null)
const hexView = ref(null)
watch(detail, () => { highlightedField.value = null })

async function highlightField(field) {
  highlightedField.value = field
  await nextTick()
  const mark = hexView.value?.querySelector('mark')
  const pane = mark?.closest('.pane-body')
  if (pane) pane.scrollTop += mark.getBoundingClientRect().top - pane.getBoundingClientRect().top - 32
}

function highlights(offset, hex, ascii) {
  const field = highlightedField.value
  if (!field || field.offset >= offset + hex.length || field.offset + field.size <= offset) {
    return [{ hex: hex.join(' '), ascii, active: false }]
  }
  const start = Math.max(0, field.offset - offset)
  const end = Math.min(hex.length, field.offset + field.size - offset)
  return [[0, start, false], [start, end, true], [end, hex.length, false]]
    .filter(([from, to]) => from < to)
    .map(([from, to, active]) => ({ hex: hex.slice(from, to).join(' '), ascii: ascii.slice(from, to), active }))
}

// 十六进制视图：每行 16 字节 + ASCII
const hexRows = computed(() => {
  const hx = detail.value?.raw_hex
  if (!hx) return []
  const rows = []
  for (let i = 0; i < hx.length; i += 32) {
    const chunk = hx.slice(i, i + 32)
    const bytes = chunk.match(/.{2}/g) || []
    const ascii = bytes.map(b => {
      const c = parseInt(b, 16)
      return c >= 32 && c < 127 ? String.fromCharCode(c) : '.'
    }).join('')
    rows.push({
      offset: (i / 2).toString(16).padStart(4, '0'),
      spans: highlights(i / 2, bytes, ascii)
    })
  }
  return rows
})


function fmtTime(t) { return t != null ? t.toFixed(3) : '—' }

let packetLookup = 0
async function locatePacket(value) {
  const num = Number(value)
  const taskId = store.currentTaskId
  const seq = ++packetLookup
  linkedPacket.value = null
  ++detailSeq
  detailLoading.value = false
  if (!Number.isInteger(num) || num < 1 || !taskId) return
  err.value = ''
  detail.value = null
  selectedId.value = null
  try {
    const hit = items.value.find(p => p.packet_number === num)
    const result = hit ? null : await api.packets(taskId, {
      page: 1, page_size: 1, number_from: num, number_to: num
    })
    if (seq !== packetLookup || taskId !== store.currentTaskId) return
    const packet = hit || result.items[0]
    if (!packet) {
      err.value = `未找到报文 #${num}`
      return
    }
    if (!hit) linkedPacket.value = packet
    await openPacket(packet)
  } catch (e) {
    if (seq === packetLookup) err.value = e.message
  }
}

watch([() => route.query.task, () => route.query.number], async ([task, number]) => {
  const taskId = Number(task)
  if (Number.isInteger(taskId) && taskId > 0 && taskId !== store.currentTaskId) {
    store.setCurrent(taskId)
    detail.value = null
    items.value = []
    page.value = 1
    await load()
    store.loadTask(taskId).catch(() => {})
  } else if (!items.value.length) {
    await load()
  }
  if (task !== route.query.task || number !== route.query.number) return
  if (task && Number(task) !== store.currentTaskId) return
  await locatePacket(number)
}, { immediate: !props.embedded })
watch(()=>props.range,()=>{page.value=1;load()})
if(props.embedded && items.value[0])openPacket(items.value[0])
</script>

<template>
  <div class="packets-page" :class="{embedded}">
    <PageNav v-if="!embedded"
      title="原始报文"
      :sub="`任务 #${store.currentTaskId || '未选择'} · 共 ${total} 条报文`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'原始报文'}]">
      <template #actions>
        <input v-model="ipFilter" class="inp sm" style="width:120px" placeholder="IP 过滤" @keyup.enter="page=1; load()" />
        <input v-model="portFilter" class="inp sm" style="width:72px" placeholder="端口" @keyup.enter="page=1; load()" />
        <input v-model="protoFilter" class="inp sm" style="width:72px" placeholder="协议" @keyup.enter="page=1; load()" />
        <input v-model="callIdFilter" class="inp sm" style="width:150px" placeholder="Call-ID" @keyup.enter="page=1; load()" />
        <button class="btn sm" @click="page=1; load()">查询</button>
      </template>
    </PageNav>

    <form v-if="embedded" class="packet-filters" @submit.prevent="page=1;load()"><input class="inp sm" v-model="ipFilter" placeholder="源或目的 IP" aria-label="IP 过滤"><input class="inp sm" v-model="protoFilter" placeholder="协议" aria-label="协议过滤"><button>查询</button><small v-if="range">捕获时间选区已应用</small></form>
    <div v-if="err" role="alert" class="err-box">{{ err }}</div>

    <div v-if="!store.currentTaskId" class="card">
      <div class="empty">尚未选择分析任务</div>
    </div>

    <div v-if="embedded || store.currentTaskId" class="tri-pane" :style="{ '--packet-list-height': listHeight + 'px' }">
      <!-- 栏 1：报文列表 -->
      <div class="pane pane-list">
        <div class="pane-head">
          报文列表
          <span v-if="linkedPacket" class="badge brand">定位 #{{ linkedPacket.packet_number }}</span>
          <span class="spacer"></span>
          <button class="mini" aria-label="上一页" :disabled="page <= 1" @click="page--; load()"><AppIcon name="prev" /></button>
          <span class="mono-sm">{{ page }}</span>
          <button class="mini" aria-label="下一页" :disabled="page * pageSize >= total" @click="page++; load()"><AppIcon name="next" /></button>
        </div>
        <div class="pane-body">
          <table class="pkt-tbl">
            <thead>
              <tr><th :aria-sort="descending ? 'descending' : 'ascending'"><button aria-label="切换报文号排序" @click="descending=!descending;page=1;load()">No. {{descending?'↓':'↑'}}</button></th><th>时间</th><th>源</th><th>目的</th><th>协议</th><th>长度</th><th>信息</th></tr>
            </thead>
            <tbody v-if="!listLoading" class="page-content-in">
              <tr v-for="p in visiblePackets" :key="p.id"
                  :class="{ active: selectedId === p.id }"
                  tabindex="0" :aria-selected="selectedId === p.id"
                  @click="openPacket(p)" @keydown.enter.prevent="openPacket(p)" @keydown.space.prevent="openPacket(p)">
                <td class="mono">{{ p.packet_number }}</td>
                <td class="num">{{ fmtTime(p.timestamp) }}</td>
                <td class="mono-sm truncate">{{ p.source_ip }}</td>
                <td class="mono-sm truncate">{{ p.destination_ip }}</td>
                <td><span class="proto">{{ p.protocol }}</span></td>
                <td class="num">{{ p.length }}</td><td :title="p.summary">{{p.summary || '—'}}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="listLoading" class="empty">读取中…</div><div v-else-if="!visiblePackets.length && !err" class="empty">无匹配报文</div>
        </div>
      </div>

      <!-- 栏 2：协议树 -->
      <PaneDivider v-if="!embedded" v-model="listHeight" horizontal class="packet-divider" label="调整报文列表高度" :min="180" :max="480" />
      <div class="pane pane-tree">
        <div class="pane-head">
          协议详情
          <span class="spacer"></span>

        </div>
        <div class="pane-body scroll">
          <div v-if="detailLoading" class="empty">加载中…</div>
          <div v-else-if="!detail" class="empty">
            从左侧选择一条报文
            <div class="hint">点击可查看协议分层与原始字节</div>
          </div>

          <template v-else>
            <div>
              <details open v-for="(layer, li) in detail.layers" :key="li" class="layer">
                <summary class="layer-name">{{ layer.name }}</summary>
                <div class="layer-fields">
                  <div v-for="(f, fi) in layer.fields" :key="fi" class="field"
                       :style="{ paddingLeft: (f.indent || 0) * 2 + 'px' }">
                    <button v-if="f.size" type="button" class="field-link" :aria-pressed="highlightedField === f"
                            @click="highlightField(f)">{{ f.name }}</button>
                    <span v-else class="fname">{{ f.name }}</span>
                    <span class="fval mono">{{ f.value }}</span>
                  </div>
                </div>
              </details>
              <div v-if="!detail.layers?.length" class="empty">该报文无协议树数据</div>
            </div>

          </template>
        </div>
      </div>

      <!-- 栏 3：字段摘要 -->
      <div v-panel-change="detail?.id" class="pane pane-info">
        <div class="pane-head">原始字节 · HEX / ASCII</div>
        <div class="pane-body scroll">
          <div v-if="!detail" class="empty">—</div>
                      <div v-if="detail && !detailLoading" ref="hexView" class="hex-view">
              <div class="hex-head">
                <span class="ho">偏移</span>
                <span class="hh">十六进制</span>
                <span class="ha">ASCII</span>
              </div>
              <div v-for="row in hexRows" :key="row.offset" class="hex-row">
                <span class="ho">{{ row.offset }}</span>
                <span class="hh"><template v-for="(part, index) in row.spans" :key="index">{{ index ? ' ' : '' }}<component :is="part.active ? 'mark' : 'span'">{{ part.hex }}</component></template></span>
                <span class="ha"><component v-for="(part, index) in row.spans" :key="index" :is="part.active ? 'mark' : 'span'">{{ part.ascii }}</component></span>
              </div>
              <div v-if="!hexRows.length" class="empty">无原始字节</div>
            </div>
          <details v-if="detail && !detailLoading"><summary>索引字段</summary>
            <div class="info-row"><span>报文号</span><b class="mono">{{ detail.packet_number }}</b></div>
            <div class="info-row"><span>时间</span><b class="mono">{{ detail.timestamp?.toFixed(6) }}s</b></div>
            <div class="info-row"><span>协议</span><b>{{ detail.protocol }}</b></div>
            <div class="info-row"><span>长度</span><b>{{ detail.length }} bytes</b></div>
            <div class="info-row"><span>源</span><b class="mono">{{ detail.source_ip }}:{{ detail.source_port ?? '-' }}</b></div>
            <div class="info-row"><span>目的</span><b class="mono">{{ detail.destination_ip }}:{{ detail.destination_port ?? '-' }}</b></div>
            <div class="info-row" v-if="detail.call_id"><span>Call-ID</span><b class="mono truncate">{{ detail.call_id }}</b></div>
            <div class="info-row" v-if="detail.ssrc"><span>SSRC</span><b class="mono">0x{{ detail.ssrc.toString(16) }}</b></div>
            <div class="info-row" v-if="detail.session_id"><span>会话</span><b>#{{ detail.session_id }}</b></div>
            <div class="info-row full"><span>摘要</span><b class="mono-sm">{{ detail.summary }}</b></div>
          </details>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.packets-page {
  padding: 26px 28px 24px; min-width: 0; margin: 0 auto;
  height: 100%; display: flex; flex-direction: column;
}

.tri-pane {
  flex: 1; min-height: 0;
  display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);
  grid-template-rows: var(--packet-list-height) 10px minmax(230px, 34vh);
  border:1px solid var(--line); border-radius:var(--radius); overflow:hidden;
}
.packets-page:not(.embedded) .pane-list { grid-column:1/-1; border-right:0; border-bottom:1px solid var(--line); }
@media (max-width:760px) {
  .packets-page:not(.embedded) .tri-pane { grid-template-columns:minmax(0,1fr); grid-template-rows:var(--packet-list-height) 10px 250px 250px; }
}
.pane {
  background: var(--surface); border-right: 1px solid var(--line-2);
  display: flex; flex-direction: column;
  min-height: 0; overflow: hidden;
}
.pane:last-child { border-right:0; }
@media (max-width: 1080px) {
  .pane { border-right:0; border-bottom:1px solid var(--line-2); }
  .pane:last-child { border-bottom:0; }
}
@media (851px <= width <= 1080px) { .packets-page:not(.embedded) .pane-tree { border-bottom:0; } }
.pane-head {
  display: flex; align-items: center; gap: 8px;
  min-height:48px; padding: 10px 14px; background: var(--surface);
  border-bottom: 1px solid var(--line-2);
  font-size: 13px; font-weight: 650; flex: none;
}
.pane-head::before { content:''; width:3px; height:14px; background:var(--brand); border-radius:2px; }
.pane-body { flex: 1; overflow: auto; min-height: 0; }
.pane-body.scroll { padding: 10px 12px; }

.mini {
  width: 20px; height: 20px; padding: 0;
  background: var(--panel-3); border: 1px solid var(--border);
  border-radius: 3px; color: var(--text-2); cursor: pointer;
  font-family: inherit; font-size: 12px; line-height: 1;
}
.mini:disabled { opacity: .4; cursor: not-allowed; }

.pkt-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.pkt-tbl th {
  position: sticky; top: 0; z-index: 2;
  background: var(--panel-2); color: var(--text-3);
  font-size: 11.5px; font-weight: 600; text-align: left;
  padding: 6px 8px; border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.pkt-tbl td {
  padding: 5px 8px; border-bottom: 1px solid var(--border);
  color: var(--text-2);
}
.pkt-tbl tbody tr { cursor: pointer; }
.pkt-tbl tbody tr:hover { background: var(--surface-2); }
.pkt-tbl tbody tr.active { background: var(--surface-3); }
.pkt-tbl tbody tr.active td:first-child { box-shadow: inset 3px 0 0 var(--brand); }
.pkt-tbl tbody tr:focus-visible { outline:2px solid var(--brand); outline-offset:-2px; }
.pkt-tbl td.num { text-align: right; font-variant-numeric: tabular-nums; }
.pane-info .empty { text-align: left; padding: 14px 12px; }



.layer { margin-bottom: 12px; }
.layer-name {
  font-size: 11.5px; font-weight: 600; color: var(--text-3);
  padding: 4px 0; border-bottom: 1px solid var(--border); margin-bottom: 5px;
}
.layer-fields { display: flex; flex-direction: column; gap: 1px; }
.field {
  display: flex; gap: 10px; font-size: 12px; padding: 2px 4px;
  border-radius: 2px;
}
.field:hover { background: var(--panel-2); }
.fname { color: var(--text-3); flex: none; min-width: 130px; max-width: 180px; }
.fval { color: var(--text-2); word-break: break-all; }

.hex-view { font-family: var(--font-mono); font-size: 12px; }
.hex-head, .hex-row { display: flex; gap: 12px; line-height: 1.75; }
.hex-head {
  color: var(--text-3); font-size: 11.5px; border-bottom: 1px solid var(--border);
  padding-bottom: 4px; margin-bottom: 4px; position: sticky; top: 0;
  background: var(--panel);
}
.hex-row:hover { background: var(--panel-2); }
.ho { color: var(--text-4); width: 42px; flex: none; }
.hh { color: var(--text-2); flex: 1; letter-spacing: .5px; }
.ha { color: var(--text-3); width: 140px; flex: none; }

.info-row {
  display: flex; gap: 10px; font-size: 12px; padding: 5px 0;
  border-bottom: 1px solid var(--border); align-items: baseline;
}
.info-row span { color: var(--text-3); width: 62px; flex: none; font-size: 12px; }
.info-row b { color: var(--text-2); font-weight: 500; word-break: break-all; }
.info-row.full { flex-direction: column; gap: 3px; }

.err-box {
  background: var(--critical-soft); border-left: 2px solid var(--critical);
  border-radius: 0; padding: 10px 12px; font-size: 12.5px;
  color: var(--critical); margin-bottom: 14px;
}
.packets-page.embedded{padding:0;height:auto;max-width:none}.embedded .tri-pane{grid-template-columns:minmax(0,1.45fr) minmax(0,.95fr) minmax(0,1.05fr);height:190px;min-height:0;border:0}.embedded .pane{min-height:0}.pane-body{overflow:auto}.packet-filters{display:flex;align-items:center;gap:8px;padding:6px 12px}.packet-filters input{width:125px}.pane-list td:last-child{max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.layer summary{cursor:pointer}
@media(max-width:850px){.embedded .tri-pane{grid-template-columns:minmax(0,1fr);height:auto}.embedded .pane{height:220px}}
@media(max-width:650px){.packets-page:not(.embedded){padding:16px}.packet-filters{flex-wrap:wrap}.packet-filters input{width:min(125px,100%)}}
.packet-divider { grid-column:1/-1; background:var(--bg-2); }
.embedded .tri-pane { grid-template-rows:minmax(0,1fr); }
@media(max-width:850px) { .embedded .tri-pane { grid-template-rows:auto; } }
.field-link { color:var(--brand-lt); font:inherit; border:0; background:none; padding:0; text-align:start; cursor:pointer; }
.field-link[aria-pressed="true"], .hex-row mark { background:var(--bg-selected); color:var(--brand-lt); }
.hex-row mark { font:inherit; }
</style>
