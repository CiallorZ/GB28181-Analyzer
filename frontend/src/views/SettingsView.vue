<script setup>
import InterfacePreferences from '../components/InterfacePreferences.vue'
import { ref, onMounted } from 'vue'
import { api } from '../api/client'
import PageNav from '../components/PageNav.vue'

const health = ref(null)
const rules = ref([])
const err = ref('')

onMounted(async () => {
  try {
    health.value = await api.health()
    const r = await api.rules()
    rules.value = r.rules || []
  } catch (e) { err.value = e.message }
})
</script>

<template>
  <div class="page">
    <PageNav
      title="系统设置"
      sub="运行环境与诊断规则说明"
      :crumbs="[{label:'工作台', to:'/'}, {label:'系统设置'}]" />

    <InterfacePreferences />
    <div v-if="err" class="err-box">{{ err }}</div>

    <div class="card mb-16">
      <div class="card-head">运行环境</div>
      <div class="card-body">
        <div class="kv-grid" v-if="health">
          <div><span>服务状态</span><b class="text-ok">运行中</b></div>
          <div><span>版本</span><b>{{ health.version }}</b></div>
          <div><span>数据库</span><b>{{ health.database }}</b></div>
          <div>
            <span>tshark</span>
            <b :class="health.dependencies?.tshark ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.tshark ? '可用' : '缺失' }}
            </b>
          </div>
          <div>
            <span>ffmpeg</span>
            <b :class="health.dependencies?.ffmpeg ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.ffmpeg ? '可用' : '缺失' }}
            </b>
          </div>
          <div>
            <span>ffprobe</span>
            <b :class="health.dependencies?.ffprobe ? 'text-ok' : 'text-critical'">
              {{ health.dependencies?.ffprobe ? '可用' : '缺失' }}
            </b>
          </div>
          <div class="full"><span>tshark 路径</span><b class="mono-sm">{{ health.tshark_path || '—' }}</b></div>
          <div class="full"><span>ffmpeg 路径</span><b class="mono-sm">{{ health.ffmpeg_path || '—' }}</b></div>
        </div>
      </div>
    </div>

    <div class="card mb-16">
      <div class="card-head">
        诊断规则清单
        <span class="count-badge">
          {{ rules.filter(r => r.implemented).length }} / {{ rules.length }} 已接入
        </span>
      </div>
      <div class="card-body tight">
        <table class="tbl">
          <thead><tr><th>规则 ID</th><th>名称</th><th>状态</th></tr></thead>
          <tbody>
            <tr v-for="r in rules" :key="r.id">
              <td class="mono text-dim">{{ r.id }}</td>
              <td>{{ r.name }}</td>
              <td>
                <span class="badge" :class="r.implemented ? 'ok' : 'unknown'">
                  {{ r.implemented ? '已接入' : '规划中' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-head">分析局限说明</div>
      <div class="card-body">
        <div class="limits">
          <div class="limit-item">
            <b>分析结果仅反映抓包点观察到的流量</b>
            <p>本平台的所有指标均由上传的抓包文件计算得出。抓包点之外的网络状况、
              客户端实际播放效果，无法从单点抓包推断。</p>
          </div>
          <div class="limit-item">
            <b>SIP 成功 ≠ 媒体成功 ≠ 播放成功</b>
            <p>SIP 200 OK 只代表信令层同意建立会话。媒体是否真正传输、
              能否解码、播放器是否显示画面，是三个独立层面，本平台分别标注。</p>
          </div>
          <div class="limit-item">
            <b>RTP 序号缺口 ≠ 网络丢包</b>
            <p>序号缺口可能来自真实丢包、抓包缓冲区溢出、或抓包点位于会话中途。
              TCP 承载时尤其不能直接判定为丢包，平台会标注证据等级。</p>
          </div>
          <div class="limit-item">
            <b>无法计算的指标不显示为 0</b>
            <p>缺少起止事件时，指标显示为「无法计算」或「—」，
              以免把「没有数据」误解为「数据为 0」。</p>
          </div>
          <div class="limit-item">
            <b>RTP 首包 ≠ 视频首帧</b>
            <p>首个 RTP 包到达不代表画面已可显示。视频首帧需要解码关键帧，
              当前帧结构统计与视频重建不能证明客户端已显示首帧。</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.h1 { font-size: 20px; font-weight: 600; }
.sub { font-size: 12.5px; color: var(--text-3); margin-top: 3px; }
.kv-grid {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0 26px;
  border-top: 1px solid var(--line);
}
.kv-grid > div {
  display: flex; flex-direction: column; gap: 3px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.kv-grid > div.full { grid-column: 1 / -1; }
.kv-grid span { color: var(--text-4); width: auto; font-size: 11.5px; }
.kv-grid b { color: var(--text); font-weight: 500; font-size: 13px; font-family: var(--font-mono); word-break: break-all; }
@media (max-width: 860px) { .kv-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px) { .kv-grid { grid-template-columns: 1fr; } }
.count-badge {
  font-size: 11px; padding: 1px 7px; border-radius: 99px;
  background: var(--panel-3); color: var(--text-3);
}
.limits { display: flex; flex-direction: column; gap: 16px; }
.limit-item {
  padding-left: 12px; border-left: 2px solid var(--border-2);
}
.limit-item b {
  display: block; font-size: 13px; color: var(--text);
  font-weight: 600; margin-bottom: 5px;
}
.limit-item p {
  font-size: 12.5px; color: var(--text-3); line-height: 1.75;
}
.err-box {
  background: var(--critical-bg); border-left: 3px solid var(--critical);
  border-radius: var(--radius); padding: 12px 14px; font-size: 13px;
  color: var(--critical); margin-bottom: 14px;
}
</style>
