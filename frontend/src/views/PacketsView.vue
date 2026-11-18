<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'
import { useTaskStore } from '../stores/task'

const route = useRoute()
const store = useTaskStore()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 200
const ipFilter = ref('')
const portFilter = ref('')
const protoFilter = ref('')
const callIdFilter = ref('')
const err = ref('')

const detail = ref(null)
const detailLoading = ref(false)
const viewMode = ref('tree')   // tree | hex

async function load() {
  if (!store.currentTaskId) return
  try {
    const r = await api.packets(store.currentTaskId, {
      page: page.value, page_size: pageSize,
      ip: ipFilter.value || undefined,
      port: portFilter.value ? Number(portFilter.value) : undefined,
      protocol: protoFilter.value || undefined,
      call_id: callIdFilter.value || undefined
    })
    items.value = r.items
    total.value = r.total
  } catch (e) { err.value = e.message }
}

async function openPacket(p) {
  detailLoading.value = true
  try {
    detail.value = await api.packet(p.id)
  } catch (e) { err.value = e.message }
  finally { detailLoading.value = false }
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
      hex: bytes.join(' '),
      ascii
    })
  }
  return rows
})

const selectedId = computed(() => detail.value?.id)

function fmtTime(t) { return t != null ? t.toFixed(3) : '—' }

onMounted(async () => {
  await load()
  // 支持从别的页面带 packet number 跳转
  const num = Number(route.query.number)
  if (num) {
    const hit = items.value.find(p => p.packet_number === num)
    if (hit) openPacket(hit)
    else {
      // 换页查找
      const r = await api.packets(store.currentTaskId, {
        page: 1, page_size: 500, number_from: num, number_to: num
      })
      if (r.items.length) openPacket(r.items[0])
    }
  }
})

watch(() => route.query.number, (v) => {
  const num = Number(v)
  if (!num) return
  const hit = items.value.find(p => p.packet_number === num)
  if (hit) openPacket(hit)
})
</script>

<template>
  <div class="packets-page">
    <PageNav
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

    <div v-if="err" class="err-box">{{ err }}</div>

    <div v-if="!store.currentTaskId" class="card">
      <div class="empty">尚未选择分析任务</div>
    </div>

    <div v-else class="tri-pane">
      <!-- 栏 1：报文列表 -->
      <div class="pane pane-list">
        <div class="pane-head">
          报文列表
          <span class="spacer"></span>
          <button class="mini" :disabled="page <= 1" @click="page--; load()">‹</button>
          <span class="mono-sm">{{ page }}</span>
          <button class="mini" :disabled="page * pageSize >= total" @click="page++; load()">›</button>
        </div>
        <div class="pane-body">
          <table class="pkt-tbl">
            <thead>
              <tr><th>#</th><th>时间</th><th>源</th><th>目的</th><th>协议</th><th>长度</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in items" :key="p.id"
                  :class="{ active: selectedId === p.id }"
                  @click="openPacket(p)">
                <td class="mono">{{ p.packet_number }}</td>
                <td class="num">{{ fmtTime(p.timestamp) }}</td>
                <td class="mono-sm truncate">{{ p.source_ip }}</td>
                <td class="mono-sm truncate">{{ p.destination_ip }}</td>
                <td><span class="badge unknown">{{ p.protocol }}</span></td>
                <td class="num">{{ p.length }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!items.length" class="empty">无报文</div>
        </div>
      </div>

      <!-- 栏 2：协议树 -->
      <div class="pane pane-tree">
        <div class="pane-head">
          协议详情
          <span class="spacer"></span>
          <div class="seg">
            <button :class="{ on: viewMode === 'tree' }" @click="viewMode = 'tree'">协议树</button>
            <button :class="{ on: viewMode === 'hex' }" @click="viewMode = 'hex'">十六进制</button>
          </div>
        </div>
        <div class="pane-body scroll">
          <div v-if="detailLoading" class="empty">加载中…</div>
          <div v-else-if="!detail" class="empty">
            从左侧选择一条报文
            <div class="hint">点击可查看协议分层与原始字节</div>
          </div>

          <template v-else>
            <div v-if="viewMode === 'tree'">
              <div v-for="(layer, li) in detail.layers" :key="li" class="layer">
                <div class="layer-name">{{ layer.name }}</div>
                <div class="layer-fields">
                  <div v-for="(f, fi) in layer.fields" :key="fi" class="field"
                       :style="{ paddingLeft: (f.indent || 0) * 2 + 'px' }">
                    <span class="fname">{{ f.name }}</span>
                    <span class="fval mono">{{ f.value }}</span>
                  </div>
                </div>
              </div>
              <div v-if="!detail.layers?.length" class="empty">该报文无协议树数据</div>
            </div>

            <div v-else class="hex-view">
              <div class="hex-head">
                <span class="ho">偏移</span>
                <span class="hh">十六进制</span>
                <span class="ha">ASCII</span>
              </div>
              <div v-for="row in hexRows" :key="row.offset" class="hex-row">
                <span class="ho">{{ row.offset }}</span>
                <span class="hh">{{ row.hex }}</span>
                <span class="ha">{{ row.ascii }}</span>
              </div>
              <div v-if="!hexRows.length" class="empty">无原始字节</div>
            </div>
          </template>
        </div>
      </div>

      <!-- 栏 3：字段摘要 -->
      <div class="pane pane-info">
        <div class="pane-head">报文字段</div>
        <div class="pane-body scroll">
          <div v-if="!detail" class="empty">—</div>
          <template v-else>
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
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.packets-page { padding: 20px 24px 24px; height: 100%; display: flex; flex-direction: column; }
.h1 { font-size: 20px; font-weight: 600; }
.sub { font-size: 12.5px; color: var(--text-3); margin-top: 3px; }
.inp {
  height: 30px; width: 130px; padding: 0 10px;
  background: var(--bg-2); border: 1px solid var(--border);
  border-radius: var(--radius-sm); color: var(--text);
  font-size: 12.5px; font-family: inherit;
}
.inp.sm { width: 78px; }
.inp:focus { outline: none; border-color: var(--accent); }

.tri-pane {
  flex: 1; min-height: 0;
  display: grid; grid-template-columns: 340px 1fr 260px;
  gap: 12px;
}
@media (max-width: 1500px) { .tri-pane { grid-template-columns: 300px 1fr 220px; } }

.pane {
  background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius); display: flex; flex-direction: column;
  min-height: 0; overflow: hidden;
}
.pane-head {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 13px; background: var(--panel-2);
  border-bottom: 1px solid var(--border);
  font-size: 12px; font-weight: 600; flex: none;
}
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
.pkt-tbl tbody tr:hover { background: var(--panel-2); cursor: pointer; }
.pkt-tbl tbody tr.active { background: var(--accent-bg); }
.pkt-tbl td.num { text-align: right; font-variant-numeric: tabular-nums; }

.seg { display: flex; gap: 0; border: 1px solid var(--border); border-radius: 4px; overflow: hidden; }
.seg button {
  padding: 2px 9px; font-size: 11.5px; background: var(--panel-3);
  border: none; color: var(--text-3); cursor: pointer; font-family: inherit;
}
.seg button.on { background: var(--accent); color: #fff; }

.layer { margin-bottom: 12px; }
.layer-name {
  font-size: 12px; font-weight: 600; color: var(--accent);
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
  background: var(--critical-bg); border-left: 3px solid var(--critical);
  border-radius: var(--radius); padding: 12px 14px; font-size: 13px;
  color: var(--critical); margin-bottom: 14px;
}
</style>
