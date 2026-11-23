<script setup>
/**
 * SIP 信令梯形图（Ladder Diagram）
 *
 * ⚠️ 实现要点：SVG 内的 v-for 必须用字符串拼装 + v-html 渲染。
 * Vue 3 编译器在 <svg> 内对 v-for 生成的元素会调用 createElementVNode
 * （HTML 命名空间），浏览器会丢弃这些节点，导致图形不显示。
 * 用 v-html 注入由字符串拼出的 SVG 才能保证命名空间正确。
 */
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({
  messages: { type: Array, default: () => [] }
})
const emit = defineEmits(['select'])

const svgContainer = ref(null)
const selected = ref(null)
const zoom = ref(1)
const ROW_H = 30
watch(() => props.messages, () => { selected.value = null })

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]))
}

/* ---------------- 参与方 ---------------- */
const parties = computed(() => {
  const list = props.messages || []
  const seen = []
  list.forEach(m => {
    if (m.source_ip && !seen.includes(m.source_ip)) seen.push(m.source_ip)
    if (m.destination_ip && !seen.includes(m.destination_ip)) seen.push(m.destination_ip)
  })
  if (list.some(m => !m.source_ip || !m.destination_ip)) seen.push('')
  return seen.map((ip) => {
    const sentInvite = list.some(m =>
      m.method === 'INVITE' && m.is_request && m.source_ip === ip)
    const recvInvite = list.some(m =>
      m.method === 'INVITE' && m.is_request && m.destination_ip === ip)
    let label = '端点', color = 'var(--text-4)'
    if (sentInvite) { label = '点播方'; color = 'var(--info)' }
    else if (recvInvite) { label = '被点播方'; color = 'var(--text-2)' }
    return { ip, label: ip ? label : '未知端点', color }
  })
})

function laneX(ip, list) {
  const i = list.findIndex(p => p.ip === (ip || ''))
  if (i < 0) return 500
  if (list.length === 1) return 500
  const pad = 110
  return pad + i * ((1000 - pad * 2) / (list.length - 1))
}

/* ---------------- 消息样式 ---------------- */
const KEY_METHODS = new Set(['INVITE', 'ACK', 'BYE', 'CANCEL'])

function styleOf(m) {
  if (m.is_request) {
    const meth = m.method || 'REQ'
    if (meth === 'INVITE') return { color: 'var(--info)', label: 'INVITE', marker: 'arwReq' }
    if (meth === 'BYE') return { color: 'var(--text-2)', label: 'BYE', marker: 'arwProv' }
    if (meth === 'ACK') return { color: 'var(--ok)', label: 'ACK', marker: 'arwOk' }
    return { color: 'var(--info)', label: meth, marker: 'arwReq' }
  }
  const code = String(m.status_code || '')
  if (code.startsWith('2')) return { color: 'var(--ok)', label: code, marker: 'arwOk' }
  if (code.startsWith('1')) return { color: 'var(--text-4)', label: code, marker: 'arwProv' }
  return { color: 'var(--critical)', label: code || 'ERR', marker: 'arwErr' }
}

const svgH = computed(() =>
  Math.max(240, (props.messages || []).length * ROW_H + 76))

/* ---------------- 生成 SVG 字符串 ---------------- */
const svgHtml = computed(() => {
  const list = parties.value
  const msgs = props.messages || []
  const H = svgH.value
  const out = []

  out.push(`<defs>
    <marker id="arwReq" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="var(--info)"/></marker>
    <marker id="arwOk" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="var(--ok)"/></marker>
    <marker id="arwErr" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="var(--critical)"/></marker>
    <marker id="arwProv" viewBox="0 0 10 10" refX="9" refY="5"
      markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="var(--text-4)"/></marker>
  </defs>`)

  // 参与方立柱 + 头部卡片
  list.forEach(p => {
    const x = laneX(p.ip, list)
    out.push(`<line x1="${x}" y1="56" x2="${x}" y2="${H - 20}"
      stroke="var(--line-2)" stroke-width="1" stroke-dasharray="4 4" opacity=".9"/>`)
    out.push(`<rect x="${x - 62}" y="8" width="124" height="38" rx="8"
      fill="var(--surface-2)" stroke="var(--line-2)" stroke-width="1"/>`)
    out.push(`<circle cx="${x - 46}" cy="27" r="4" fill="${p.color}"/>`)
    out.push(`<text x="${x + 4}" y="24" text-anchor="middle"
      fill="var(--text)" font-size="13" font-weight="600">${esc(p.label)}</text>`)
    out.push(`<text x="${x + 4}" y="37" text-anchor="middle"
      fill="var(--text-3)" font-size="11.5" font-family="monospace">${esc(p.ip || '地址缺失')}</text>`)
  })

  // 消息行
  msgs.forEach((m, i) => {
    const st = styleOf(m)
    const y = 60 + i * ROW_H
    const x1 = laneX(m.source_ip, list)
    const x2 = laneX(m.destination_ip, list)
    const key = !!(m.method && KEY_METHODS.has(m.method))
    const hl = selected.value === i

    // 行底
    if (hl) {
      out.push(`<rect x="0" y="${y - 12}" width="1000" height="${ROW_H - 4}"
        fill="${selected.value === i ? 'var(--surface-3)' : 'var(--surface-2)'}" rx="5"/>`)
    }

    // 连线
    if (x1 === x2) {
      out.push(`<path d="M${x1} ${y} h28 v10 h-28" fill="none" stroke="${st.color}" stroke-width="1.4" marker-end="url(#${st.marker})"/>`)
    } else out.push(`<line x1="${x1}" y1="${y}" x2="${x2}" y2="${y}"
      stroke="${st.color}" stroke-width="${key ? 2 : 1.4}"
      opacity="${hl ? 1 : .84}" marker-end="url(#${st.marker})"/>`)

    // 方法标签（贴源端）
    const leftSide = x1 <= x2
    const lx = leftSide ? x1 + 7 : x1 - 67
    const tx = leftSide ? x1 + 37 : x1 - 37
    out.push(`<rect x="${lx}" y="${y - 9}" width="60" height="17" rx="4"
      fill="${st.color}" opacity="${key ? .16 : .09}"/>`)
    out.push(`<text x="${tx}" y="${y + 3}" text-anchor="middle"
      fill="${st.color}" font-size="12" font-family="monospace"
      font-weight="600">${esc(st.label)}</text>`)

    // 时间
    if (m.timestamp != null) {
      out.push(`<text x="994" y="${y + 3}" text-anchor="end"
        fill="var(--text-3)" font-size="11.5" font-family="monospace">${
          Number(m.timestamp).toFixed(3)}s</text>`)
    }

    // 国标命令
    if (m.gb_command) {
      out.push(`<rect x="4" y="${y - 8}" width="72" height="15" rx="3"
        fill="#D70D19" opacity=".14"/>`)
      out.push(`<text x="40" y="${y + 3}" text-anchor="middle"
        fill="#F5323E" font-size="8.5" font-family="monospace">${
          esc(m.gb_command)}</text>`)
    }

    // 透明热区（承接鼠标事件）
    out.push(`<rect class="hit" data-idx="${i}" x="0" y="${y - 12}"
      width="1000" height="${ROW_H - 4}" fill="transparent"
      role="button" tabindex="0" aria-label="${esc(st.label)}，报文 ${esc(m.packet_id || '未知')}，${esc(m.source_ip || '未知端点')} 到 ${esc(m.destination_ip || '未知端点')}" style="cursor:pointer"/>`)
  })

  return `<svg class="ladder-svg" viewBox="0 0 1000 ${H}" role="group" aria-label="SIP 信令交互，共 ${msgs.length} 条消息"
    style="height:${H * zoom.value}px;width:100%;display:block"
    xmlns="http://www.w3.org/2000/svg">${out.join('')}</svg>`
})

/* ---------------- 交互 ---------------- */
function onSvgClick(e) {
  const t = e.target
  if (t && t.classList?.contains('hit')) {
    const idx = Number(t.dataset.idx)
    const m = props.messages[idx]
    if (m) {
      selected.value = idx
      emit('select', m)
    }
  }
}

function onSvgKey(e) {
  if ((e.key === 'Enter' || e.key === ' ') && e.target?.classList?.contains('hit')) {
    e.preventDefault()
    const index = e.target.dataset.idx
    onSvgClick(e)
    nextTick(() => svgContainer.value?.querySelector(`.hit[data-idx="${index}"]`)?.focus())
  }
}

const failures = computed(() => props.messages.flatMap((message, index) =>
  !message.is_request && message.status_code >= 400 && message.status_code < 700 ? [index] : []))

async function nextFailure() {
  const index = failures.value.find(i => i > (selected.value ?? -1)) ?? failures.value[0]
  if (index === undefined) return
  selected.value = index
  emit('select', props.messages[index])
  await nextTick()
  svgContainer.value?.querySelector(`.hit[data-idx="${index}"]`)?.scrollIntoView({ block: 'nearest' })
}

function onWheel(e) {
  if (!e.ctrlKey && !e.metaKey) return
  e.preventDefault()
  const next = zoom.value + (e.deltaY > 0 ? -0.1 : 0.1)
  zoom.value = Math.min(2, Math.max(0.6, +next.toFixed(1)))
}
</script>

<template>
  <div class="ladder-wrap" @wheel="onWheel">
    <div class="ladder-tools">
      <button v-if="failures.length" class="btn xs" @click="nextFailure">定位失败响应 · {{ failures.length }}</button>
      <span class="lt-hint">Ctrl + 滚轮缩放</span>
      <span class="spacer"></span>
      <button class="btn icon xs" aria-label="缩小时序图" @click="zoom = Math.max(0.6, +(zoom - 0.1).toFixed(1))">−</button>
      <span class="lt-zoom mono">{{ Math.round(zoom * 100) }}%</span>
      <button class="btn icon xs" aria-label="放大时序图" @click="zoom = Math.min(2, +(zoom + 0.1).toFixed(1))">+</button>
      <button class="btn icon xs" @click="zoom = 1">重置</button>
    </div>

    <div class="ladder-scroll">
      <!-- eslint-disable-next-line vue/no-v-html -->
      <div ref="svgContainer" v-html="svgHtml" @click="onSvgClick" @keydown="onSvgKey"></div>
    </div>

    <div v-if="!messages.length" class="empty">
      没有可展示的信令消息
    </div>
  </div>
</template>

<style scoped>
.ladder-wrap {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
}
.ladder-tools {
  display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
  padding: 8px 12px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--line);
}
.lt-hint { font-size: 11.5px; color: var(--text-4); }
.lt-zoom {
  font-size: 11.5px; color: var(--text-3);
  min-width: 38px; text-align: center;
}

.ladder-scroll {
  max-height: 580px;
  overflow: auto;
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: 40px 40px;
}
.ladder-scroll > div { min-width: 700px; }
.ladder-scroll :deep(.hit:focus-visible) { outline: 2px solid var(--brand); outline-offset: -2px; }
.ladder-scroll :deep(.hit:hover) { fill: var(--surface-3); fill-opacity: .28; }
</style>
