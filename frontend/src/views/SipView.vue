<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useTaskStore } from '../stores/task'
import SipLadder from '../components/SipLadder.vue'
import PageNav from '../components/PageNav.vue'

const router = useRouter()
const store = useTaskStore()

const sessions = ref([])
const selected = ref(null)
const sip = ref([])
const filterMethod = ref('')
const filterCallId = ref('')
const err = ref('')
const selectedMsg = ref(null)
const loading = ref(false)

async function loadSessions() {
  if (!store.currentTaskId) return
  try {
    const r = await api.sessions(store.currentTaskId, { page_size: 50 })
    sessions.value = r.items
    if (r.items.length) await selectSession(r.items[0].id)
  } catch (e) { err.value = e.message }
}

async function selectSession(id) {
  selected.value = id
  loading.value = true
  try {
    const r = await api.sessionSip(id)
    sip.value = r.items || []
    selectedMsg.value = null
  } catch (e) { err.value = e.message }
  finally { loading.value = false }
}

const methods = computed(() => {
  const s = new Set()
  sip.value.forEach(m => s.add(m.method || String(m.status_code)))
  return [...s].sort()
})

const filtered = computed(() => {
  let a = sip.value
  if (filterMethod.value) {
    a = a.filter(m => (m.method || String(m.status_code)) === filterMethod.value)
  }
  if (filterCallId.value) {
    a = a.filter(m => (m.call_id || '').includes(filterCallId.value))
  }
  return a
})

/* ---- 关键阶段识别 ---- */
const phases = computed(() => {
  const out = []
  const find = (pred) => sip.value.find(pred)
  const invite = find(m => m.method === 'INVITE' && m.is_request)
  const trying = find(m => m.status_code === 100)
  const ringing = find(m => m.status_code === 180)
  const ok = find(m => m.status_code === 200 && m.cseq?.includes('INVITE'))
  const ack = find(m => m.method === 'ACK' && m.is_request)
  const bye = find(m => m.method === 'BYE' && m.is_request)
  const byeOk = find(m => m.status_code === 200 && m.cseq?.includes('BYE'))

  const add = (label, obj, cls) => {
    if (obj) out.push({
      label, t: obj.timestamp, cls,
      pkt: obj.packet_id, delta: 0
    })
  }
  add('INVITE', invite, 'info')
  add('100 Trying', trying, 'prov')
  add('180 Ringing', ringing, 'prov')
  add('200 OK', ok, 'ok')
  add('ACK', ack, 'ok')
  add('BYE', bye, 'warn')
  add('200 OK', byeOk, 'ok')

  // 计算相邻间隔
  for (let i = 1; i < out.length; i++) {
    out[i].delta = +(out[i].t - out[i - 1].t).toFixed(3)
  }
  return out
})

const latency = computed(() => {
  const inv = phases.value.find(p => p.label === 'INVITE')
  const ok = phases.value.find(p => p.label === '200 OK')
  if (!inv || !ok) return null
  return +(ok.t - inv.t).toFixed(3)
})

const sessionInfo = computed(() =>
  sessions.value.find(s => s.id === selected.value) || null)

function onPick(m) { selectedMsg.value = m }

function goPacket(id) {
  if (!id) return
  router.push({ name: 'packets', query: { number: id } })
}

onMounted(loadSessions)
</script>

<template>
  <div class="page">
    <PageNav
      title="SIP 信令分析"
      :sub="`任务 #${store.currentTaskId || '未选择'} · ${sip.length} 条消息 · ${sessions.length} 个会话`"
      :crumbs="[{label:'工作台', to:'/'}, {label:'SIP 信令分析'}]">
      <template #actions>
        <select v-model="filterMethod" class="inp sm" style="width:132px">
          <option value="">全部方法</option>
          <option v-for="m in methods" :key="m" :value="m">{{ m }}</option>
        </select>
        <input v-model="filterCallId" class="inp sm" style="width:190px"
               placeholder="Call-ID 过滤" />
      </template>
    </PageNav>

    <div v-if="err" class="err-box mb-20">{{ err }}</div>

    <div v-if="!store.currentTaskId" class="sec">
      <div class="empty">
        尚未选择分析任务
        <div class="hint">请先在首页上传抓包文件</div>
      </div>
    </div>

    <div v-else class="layout">
      <!-- 会话列表 -->
      <aside class="side">
        <div class="side-head">
          会话
          <span class="cnt">{{ sessions.length }}</span>
        </div>
        <div class="side-body">
          <div v-for="s in sessions" :key="s.id"
               class="sess" :class="{ on: selected === s.id }"
               @click="selectSession(s.id)">
            <div class="se-top">
              <span class="mono-sm">#{{ s.id }}</span>
              <span class="badge" :class="s.signal_status === 'success' ? 'ok'
                : (s.signal_status === 'failed' ? 'critical' : 'warning')">
                {{ { success:'成功', failed:'失败', incomplete:'不完整', unknown:'未知' }[s.signal_status] }}
              </span>
            </div>
            <div class="se-dev mono truncate">{{ s.device_id || '—' }}</div>
            <div class="se-meta mono-sm">
              {{ s.start_time?.toFixed(2) }}s
              <template v-if="s.total_duration"> · {{ s.total_duration.toFixed(2) }}s</template>
            </div>
          </div>
          <div v-if="!sessions.length" class="empty" style="padding:30px 12px">
            无会话
          </div>
        </div>
      </aside>

      <!-- 主区 -->
      <div class="col" style="gap:16px;min-width:0">
        <!-- 阶段条 -->
        <div class="sec" v-if="phases.length">
          <div class="sec-head">
            <span class="sec-num">⚡</span>
            <span class="sec-title">信令关键阶段</span>
            <span class="spacer"></span>
            <span v-if="latency != null" class="lat-chip">
              INVITE → 200 OK <b>{{ latency }}s</b>
            </span>
          </div>
          <div class="sec-body tight">
            <div class="phase-strip">
              <div v-for="(p, i) in phases" :key="i" class="ph" :class="p.cls">
                <div class="ph-node">
                  <span class="ph-dot"></span>
                  <span v-if="i < phases.length - 1" class="ph-line"></span>
                </div>
                <div class="ph-label">{{ p.label }}</div>
                <div class="ph-time mono-sm">{{ p.t?.toFixed(3) }}s</div>
                <div v-if="i > 0" class="ph-delta mono-sm">+{{ p.delta }}s</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 梯形图 -->
        <div class="sec">
          <div class="sec-head">
            <span class="sec-num">⇄</span>
            <span class="sec-title">信令交互时序</span>
            <span class="sec-sub">{{ filtered.length }} 条</span>
            <span class="spacer"></span>
            <span class="legend">
              <i style="background:#4D6BFE"></i>请求
              <i style="background:#22c55e"></i>2xx
              <i style="background:#7d8b9a"></i>1xx
              <i style="background:#f0453a"></i>错误
            </span>
          </div>
          <div class="sec-body tight">
            <SipLadder :key="selected || 0" :messages="filtered" @select="onPick" />
          </div>
        </div>

        <!-- 消息详情 -->
        <div class="sec" v-if="selectedMsg">
          <div class="sec-head">
            <span class="sec-num">◉</span>
            <span class="sec-title">消息详情</span>
            <span class="sec-sub">#{{ selectedMsg.packet_id }}</span>
            <span class="spacer"></span>
            <button class="btn-mini" @click="goPacket(selectedMsg.packet_id)">
              查看原始报文 →
            </button>
            <button class="btn-mini" @click="selectedMsg = null">关闭</button>
          </div>
          <div class="sec-body">
            <div class="msg-grid">
              <div><span>方法 / 响应</span>
                <b class="mono">{{ selectedMsg.method || selectedMsg.status_code }}</b></div>
              <div><span>时间</span>
                <b class="mono">{{ selectedMsg.timestamp?.toFixed(6) }}s</b></div>
              <div><span>源</span>
                <b class="mono">{{ selectedMsg.source_ip }}:{{ selectedMsg.source_port }}</b></div>
              <div><span>目的</span>
                <b class="mono">{{ selectedMsg.destination_ip }}:{{ selectedMsg.destination_port }}</b></div>
              <div class="wide"><span>Call-ID</span>
                <b class="mono">{{ selectedMsg.call_id || '—' }}</b></div>
              <div><span>From Tag</span>
                <b class="mono">{{ selectedMsg.from_tag || '—' }}</b></div>
              <div><span>To Tag</span>
                <b class="mono">{{ selectedMsg.to_tag || '—' }}</b></div>
              <div><span>CSeq</span>
                <b class="mono">{{ selectedMsg.cseq || '—' }}</b></div>
              <div><span>国标命令</span>
                <b>{{ selectedMsg.gb_command || '—' }}</b></div>
            </div>

            <div v-if="selectedMsg.sdp" class="sdp-block">
              <div class="blk-title">SDP 协商</div>
              <div class="msg-grid">
                <div><span>连接地址</span>
                  <b class="mono">{{ selectedMsg.sdp.connection_address || '—' }}</b></div>
                <div><span>媒体</span>
                  <b class="mono">
                    {{ (selectedMsg.sdp.media || []).map(m => `${m.type}/${m.port}/${m.protocol}`).join(', ') || '—' }}
                  </b></div>
                <div><span>setup</span>
                  <b class="mono">{{ selectedMsg.sdp.setup || '—' }}</b></div>
                <div><span>y= SSRC</span>
                  <b class="mono">{{ selectedMsg.sdp.y_ssrc || '—' }}</b></div>
                <div><span>方向</span>
                  <b>{{ selectedMsg.sdp.stream_mode || '—' }}</b></div>
                <div><span>TCP</span>
                  <b>{{ selectedMsg.sdp.is_tcp ? '是' : '否' }}</b></div>
              </div>
            </div>

            <div v-if="selectedMsg.body_preview" class="sdp-block">
              <div class="blk-title">正文</div>
              <pre class="body-pre">{{ selectedMsg.body_preview }}</pre>
            </div>
          </div>
        </div>

        <!-- 消息表 -->
        <div class="sec">
          <div class="sec-head">
            <span class="sec-num">≡</span>
            <span class="sec-title">消息明细</span>
            <span class="sec-sub">{{ filtered.length }} 条</span>
          </div>
          <div class="sec-body flush" style="max-height:340px;overflow:auto">
            <table class="tbl">
              <thead>
                <tr>
                  <th>时间</th><th>方法/响应</th><th>源 → 目的</th>
                  <th>CSeq</th><th>国标</th><th>报文</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="m in filtered" :key="m.id"
                    :class="{ active: selectedMsg?.id === m.id }"
                    @click="onPick(m)">
                  <td class="mono-sm">{{ m.timestamp.toFixed(3) }}</td>
                  <td>
                    <span class="badge" :class="m.is_request
                      ? (m.method === 'INVITE' ? 'info' : m.method === 'BYE' ? 'warning' : 'unknown')
                      : (String(m.status_code).startsWith('2') ? 'ok' : 'critical')">
                      {{ m.is_request ? m.method : m.status_code }}
                    </span>
                  </td>
                  <td class="mono-sm truncate" style="max-width:240px">
                    {{ m.source_ip }} → {{ m.destination_ip }}
                  </td>
                  <td class="mono-sm">{{ m.cseq || '—' }}</td>
                  <td>
                    <span v-if="m.gb_command" class="badge brand">{{ m.gb_command }}</span>
                    <span v-else class="text-na">—</span>
                  </td>
                  <td class="mono-sm">{{ m.packet_id ? '#' + m.packet_id : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.h1 { font-size: 22px; font-weight: 680; letter-spacing: -.5px; }
.sub { font-size: 12.5px; color: var(--text-3); margin-top: 4px; }

.layout {
  display: grid;
  grid-template-columns: 232px 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1200px) { .layout { grid-template-columns: 1fr; } }

.side {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  position: sticky; top: 78px;
}
.side-head {
  padding: 11px 14px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
  font-size: 12px; font-weight: 600;
  display: flex; align-items: center; gap: 8px;
}
.cnt {
  font-size: 11.5px; padding: 0 6px;
  border-radius: 99px; background: var(--surface-3);
  color: var(--text-3); font-weight: 400;
}
.side-body { max-height: calc(100vh - 180px); overflow-y: auto; }

.sess {
  padding: 10px 13px;
  border-bottom: 1px solid var(--line);
  cursor: pointer;
  transition: .13s;
}
.sess:hover { background: var(--surface-2); }
.sess.on {
  background: var(--brand-soft);
  border-left: 2px solid var(--brand);
  padding-left: 11px;
}
.se-top {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 3px;
}
.se-dev { font-size: 12px; color: var(--text-2); }
.se-meta { color: var(--text-4); font-size: 11.5px; margin-top: 2px; }

/* 阶段条 */
.lat-chip {
  font-size: 12px; color: var(--text-3);
}
.lat-chip b { color: var(--brand-lt); font-family: var(--font-mono); }

.phase-strip {
  display: flex; gap: 0;
  overflow-x: auto; padding: 8px 0 4px;
}
.ph {
  flex: 1; min-width: 88px;
  display: flex; flex-direction: column;
  align-items: center; gap: 3px;
  position: relative;
}
.ph-node {
  width: 100%; height: 14px;
  display: flex; align-items: center; justify-content: center;
  position: relative;
}
.ph-dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: var(--text-4);
  border: 2px solid var(--surface);
  box-shadow: 0 0 0 1.5px var(--text-4);
  z-index: 2;
  transition: all .2s;
}
.ph.info .ph-dot { background: var(--info); box-shadow: 0 0 0 1.5px var(--info), 0 0 10px rgba(61,155,233,.5); }
.ph.ok .ph-dot { background: var(--ok); box-shadow: 0 0 0 1.5px var(--ok), 0 0 10px rgba(34,197,94,.5); }
.ph.warn .ph-dot { background: var(--warning); box-shadow: 0 0 0 1.5px var(--warning), 0 0 10px rgba(240,160,32,.5); }
.ph.prov .ph-dot { background: var(--text-3); box-shadow: 0 0 0 1.5px var(--text-3); }

.ph-line {
  position: absolute; top: 50%;
  left: 50%; width: 100%; height: 1.5px;
  background: var(--line-strong);
  z-index: 1;
}
.ph-label {
  font-size: 12px; color: var(--text-2);
  white-space: nowrap; font-weight: 500;
}
.ph-time { font-size: 11px; color: var(--text-4); }
.ph-delta {
  font-size: 10.5px; color: var(--brand-lt);
  background: var(--brand-soft);
  padding: 0 5px; border-radius: 3px;
}

.legend {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11.5px; color: var(--text-4);
}
.legend i {
  width: 7px; height: 7px; border-radius: 2px;
  display: inline-block; margin-left: 7px;
}

/* 消息详情 */
.msg-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 10px 24px;
}
.msg-grid > div { display: flex; gap: 10px; font-size: 12.5px; align-items: baseline; }
.msg-grid > div.wide { grid-column: 1 / -1; }
.msg-grid span { color: var(--text-3); width: 82px; flex: none; font-size: 12px; }
.msg-grid b { color: var(--text-2); font-weight: 500; word-break: break-all; }

.sdp-block { margin-top: 18px; padding-top: 16px; border-top: 1px dashed var(--line); }
.blk-title {
  font-size: 12px; color: var(--text-3);
  font-weight: 600; margin-bottom: 10px;
  letter-spacing: .3px;
}
.body-pre {
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  font-family: var(--font-mono); font-size: 12px;
  color: var(--text-2); max-height: 280px;
  overflow: auto; white-space: pre-wrap;
  word-break: break-all; line-height: 1.7;
}
</style>
