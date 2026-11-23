<script setup>
import { usePacketReplay } from '../utils/usePacketReplay'
const phases = [
  ['INVITE', '平台发起点播，提供接收媒体的地址。'],
  ['200 OK', '设备接受请求，返回协商后的媒体参数。'],
  ['ACK', '平台确认最终响应，完成会话建立。'],
  ['RTP / PS', '设备向协商地址发送封装视频的 RTP 报文。']
]
function routePath(index) {
  const y = 31 + index * 30
  return index % 2
    ? `M382 77 H350 L326 ${y} H154 L130 77 H98`
    : `M98 77 H130 L154 ${y} H326 L350 77 H382`
}
const {index, playing, play, pause, select} = usePacketReplay(() => phases.length, true)
</script>
<template>
  <section class="scope" aria-label="点播交互示意">
    <header><h2>点播交互示意</h2><button class="btn xs" @click="playing ? pause() : play()">{{playing?'暂停演示':'播放演示'}}</button></header>
    <svg viewBox="0 0 480 166" role="img" :aria-label="phases[index][0] + (index % 2 ? '，设备到平台' : '，平台到设备')">
      <g class="node" transform="translate(30 47)">
        <rect width="68" height="60" rx="13"/><g class="icon"><path d="M16 14h36q2 0 2 2v9q0 2-2 2H16q-2 0-2-2v-9q0-2 2-2z M16 33h36q2 0 2 2v9q0 2-2 2H16q-2 0-2-2v-9q0-2 2-2z M20 20h3m3 0h2m10 0h10M20 39h3m3 0h2m10 0h10 M19 28v4m30-4v4"/></g>
      </g>
      <g class="node" transform="translate(382 47)">
        <rect width="68" height="60" rx="13"/><g class="icon"><path d="m11 17 7-6 38 12-6 9-39-12z M17 23l-2 6 29 9 3-7 M48 32l3 1-2 6-4-1 M24 33l-3 9 12 4h10m0-6v12h5V40z"/></g>
      </g>
      <g v-for="(phase,i) in phases" :key="phase[0]" :class="['route',{active:i===index}]">
        <path :d="routePath(i)" pathLength="100"/>
        <path v-if="i===index" class="packet" :style="{animationPlayState:playing?'running':'paused'}" :d="routePath(i)" pathLength="100"/>
        <rect x="204" :y="21+i*30" width="72" height="19" rx="5"/><text x="240" :y="35+i*30">{{phase[0]}}</text>
      </g>
      <text class="caption" x="64" y="132">平台</text><text class="caption" x="416" y="132">设备</text>
    </svg>
    <div class="phases"><button v-for="(phase,i) in phases" :key="i" :aria-pressed="index===i" @click="select(i)">{{phase[0]}}</button></div>
    <p>{{phases[index][1]}}</p>
  </section>
</template>
<style scoped>
.scope { align-self:center; margin:18px; padding:20px; background:radial-gradient(var(--line-2) .8px,transparent .9px) 0 0/14px 14px,var(--surface-2); border:1px solid var(--line-2); border-radius:14px; min-width:0; }
header,.phases {display:flex;align-items:center;justify-content:space-between;gap:6px}h2{font-size:16px}.scope svg{display:block;width:100%;margin:15px 0 0}
.node rect,.route rect {fill:var(--surface);stroke:var(--line-strong)}.icon,.route path{fill:none;stroke:var(--text-3);stroke-width:1.6;stroke-linejoin:round;stroke-linecap:round}
.route path{stroke:var(--line-2)}.route.active path,.route.active rect{stroke:var(--brand-lt)}.route .packet{stroke-width:4;stroke-dasharray:6 94;animation:transmit 1.45s linear infinite}
@keyframes transmit{from{stroke-dashoffset:6}to{stroke-dashoffset:-94}}text{text-anchor:middle;fill:var(--text-3);font:600 12px var(--font-mono)}.active text{fill:var(--brand-lt)}.caption{fill:var(--text);font-size:14px;font-family:inherit}
.phases button{flex:1;font:600 11px var(--font-mono);padding:7px 2px;color:var(--text-2);background:var(--surface);border:1px solid var(--line-2);border-radius:5px;cursor:pointer}.phases [aria-pressed=true]{border-color:var(--brand-lt);color:var(--brand-lt)}
p{margin:12px 0 0;color:var(--text-2);font-size:13px;min-height:2.8em}@media(max-width:550px){.scope{margin:8px;padding:14px}}@media(prefers-reduced-motion:reduce){.packet{display:none}}
</style>
