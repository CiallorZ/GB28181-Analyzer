<script setup>
/**
 * 重建视频播放器
 *
 * 展示从 RTP → PS → ES 还原出的 MP4，带封面、元信息、下载。
 */
import { ref, computed, watch } from 'vue'

const props = defineProps({
  stream: { type: Object, required: true }
})

const playing = ref(false)
const loaded = ref(false)
const failed = ref(false)
const videoEl = ref(null)

const info = computed(() => {
  const s = props.stream
  const rb = s.extra?.rebuild || {}
  return {
    ok: !!rb.ok && (s.has_rebuilt_video ?? Boolean(s.rebuilt_path)),
    aligned: !!rb.aligned,
    duration: rb.duration ?? s.duration,
    psBytes: rb.ps_bytes,
    error: rb.error || s.rebuild_error,
    codec: s.codec,
    width: s.width,
    height: s.height,
    outputCodec: rb.output_codec,
    outputWidth: rb.output_width,
    outputHeight: rb.output_height,
    frames: s.frame_count
  }
})

// 转码失败时后端会回传 ffmpeg 的原始 stderr。直接把英文报错铺在画面上
// 既吓人也没法行动，这里先给结论和下一步，原始输出收进折叠区。
const failure = computed(() => {
  const raw = String(info.value.error || '').trim()
  const detail = raw.length > 480 ? raw.slice(0, 480) + '…' : raw
  if (!raw) {
    return {
      title: '这段 RTP 没有可解码的视频载荷',
      hint: '流里只有信令、空载荷或纯音频数据，没有可重建的视频帧。',
      detail: ''
    }
  }
  if (/Invalid data|could not find codec|moov|Invalid NAL|非 PS/i.test(raw)) {
    return {
      title: '抓包里的视频数据不完整，无法重建画面',
      hint: '常见原因是抓包起点在关键帧之后、只覆盖了部分 GOP，或载荷不是标准 PS/H.264 封装。可对照诊断事件中的 MED 规则确认。',
      detail
    }
  }
  if (/timeout|超时/i.test(raw)) {
    return {
      title: '视频重建超时',
      hint: '这段时间内的数据量较大或关键帧缺失，重建没有在限定时间内完成。可尝试截取包含完整 GOP 的较短抓包。',
      detail
    }
  }
  if (/No such file|ENOENT|找不到/i.test(raw)) {
    return {
      title: '临时文件已失效',
      hint: '重建产物可能已被清理，重新分析该任务即可再次生成。',
      detail
    }
  }
  return {
    title: '视频重建没有成功',
    hint: '可先查看诊断事件与编码信息，确认抓包是否覆盖了完整关键帧。',
    detail
  }
})

const videoUrl = computed(() => `/api/v1/streams/${props.stream.id}/video`)
const posterUrl = computed(() => `/api/v1/streams/${props.stream.id}/poster`)

function play() {
  if (!info.value.ok) return
  playing.value = true
  loaded.value = false
}

function onLoaded() {
  loaded.value = true
  const v = videoEl.value
  if (v) v.play().catch(() => {})
}

function onError() {
  failed.value = true
  loaded.value = false
}

function download() {
  const a = document.createElement('a')
  a.href = videoUrl.value
  a.download = `stream-${props.stream.ssrc != null ? props.stream.ssrc.toString(16) : props.stream.id}.mp4`
  a.click()
}

function fmtSize(b) {
  if (!b) return '—'
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(2) + ' MB'
}

watch(() => props.stream.id, () => {
  playing.value = false
  loaded.value = false
  failed.value = false
})
</script>

<template>
  <div class="vp" :class="{ ok: info.ok }">
    <!-- 播放区 -->
    <div class="vp-stage">
      <template v-if="info.ok">
        <video v-if="playing" ref="videoEl" class="vp-video"
               :src="videoUrl" :poster="posterUrl"
               controls playsinline
               @loadeddata="onLoaded" @error="onError"></video>

        <div v-else class="vp-cover" role="button" tabindex="0" aria-label="播放重建视频" @click="play" @keydown.enter.prevent="play" @keydown.space.prevent="play">
          <img :src="posterUrl" alt="" class="vp-poster"
               @error="(e) => e.target.style.display = 'none'" />
          <div class="vp-play">
            <AppIcon name="play" />
          </div>
          <div class="vp-badge">
            MP4 <template v-if="info.outputWidth && info.outputHeight">· {{ info.outputWidth }}×{{ info.outputHeight }}</template>
            <template v-if="info.duration"> · {{ info.duration.toFixed(2) }}s</template>
          </div>
        </div>

        <div v-if="failed" class="vp-fail">
          <div>视频加载失败</div>
          <button class="btn-mini" @click="playing = false; failed = false">返回封面</button>
        </div>
      </template>

      <div v-else class="vp-none">
        <div class="vn-icon">
          <AppIcon name="monitor" />
        </div>
        <div class="vn-title">未解出画面</div>
        <div class="vn-reason">{{ failure.title }}</div>
        <p class="vn-hint">{{ failure.hint }}</p>
        <details v-if="failure.detail" class="vn-tech">
          <summary>技术详情</summary>
          <pre>{{ failure.detail }}</pre>
        </details>
      </div>
    </div>

    <!-- 信息栏 -->
    <div class="vp-info">
      <div class="vi-row">
        <span class="vi-k">SSRC</span>
        <span class="vi-v mono">{{ stream.ssrc == null ? '未知' : '0x' + stream.ssrc.toString(16) }}</span>
      </div>
      <div class="vi-row">
        <span class="vi-k">传输</span>
        <span class="vi-v">{{ stream.transport }} · {{ stream.source_port }} → {{ stream.destination_port }}</span>
      </div>
      <template v-if="info.ok">
        <div class="vi-row">
          <span class="vi-k">源流</span>
          <span class="vi-v">
            <span class="badge brand">{{ info.codec || '未知' }}</span>
            <template v-if="info.width && info.height">{{ info.width }}×{{ info.height }}</template>
          </span>
        </div>
        <div class="vi-row">
          <span class="vi-k">预览编码</span>
          <span class="vi-v mono">{{ info.outputCodec || '未知' }}</span>
        </div>
        <div class="vi-row">
          <span class="vi-k">帧数</span>
          <span class="vi-v mono">{{ info.frames ?? '—' }}</span>
        </div>
        <div class="vi-row" v-if="info.psBytes">
          <span class="vi-k">PS 数据</span>
          <span class="vi-v mono">{{ fmtSize(info.psBytes) }}</span>
        </div>
        <div class="vi-row" v-if="info.aligned">
          <span class="vi-k">参数集</span>
          <span class="vi-v">
            <span class="badge ok" title="抓包起点不在 GOP 边界，已对齐到首个 SPS/PPS">
              已对齐
            </span>
          </span>
        </div>
      </template>
      <div class="vi-acts" v-if="info.ok">
        <button class="btn-mini" @click="download">下载 MP4</button>
        <a class="btn-mini" :href="posterUrl" target="_blank">查看封面</a>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vp {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color var(--dur) var(--ease);
}
.vp:hover { border-color: var(--line-strong); }

.vp-stage {
  position: relative;
  background: #05080d;
  aspect-ratio: 16 / 9;
  overflow: hidden;
}

.vp-video {
  width: 100%; height: 100%;
  display: block;
  object-fit: contain;
  background: #000;
}

.vp-cover {
  position: absolute; inset: 0;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.vp-poster {
  position: absolute; inset: 0;
  width: 100%; height: 100%;
  object-fit: contain;
  opacity: .82;
  transition: opacity var(--dur) var(--ease);
}
.vp-cover:hover .vp-poster {
  opacity: 1;
}
.vp-play {
  position: relative;
  width: 52px; height: 52px;
  border-radius: 50%;
  background: rgba(10, 14, 19, .74);
  border: 1px solid rgba(255, 255, 255, .35);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  padding-left: 3px;
  transition: transform var(--dur) var(--ease), background-color var(--dur) var(--ease);
}
.vp-cover:hover .vp-play { transform: scale(1.06); background: rgba(10, 14, 19, .9); }
.vp-play svg { width: 22px; height: 22px; }

.vp-badge {
  position: absolute; left: 10px; bottom: 10px;
  font-size: 10.5px; color: #fff;
  background: rgba(0, 0, 0, .62);
  backdrop-filter: blur(6px);
  padding: 3px 9px; border-radius: 5px;
  font-family: var(--font-mono);
}

.vp-fail {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 12px;
  background: rgba(0, 0, 0, .8);
  color: var(--critical); font-size: 13px;
}

.vp-none {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 7px; padding: 20px;
  background: var(--surface);
  text-align: center;
  overflow: auto;
}
.vn-icon {
  width: 44px; height: 44px;
  border-radius: 12px;
  background: var(--surface-3);
  border: 1px solid var(--line-2);
  display: flex; align-items: center; justify-content: center;
  color: var(--text-4);
}
.vn-icon svg { width: 20px; height: 20px; }
.vn-title { font-size: 13px; color: var(--text-2); font-weight: 550; }
.vn-icon { margin-bottom: 2px; }
.vn-reason {
  font-size: 12.5px; color: var(--text-2); font-weight: 550;
  line-height: 1.5; max-width: 34ch;
}
.vn-hint {
  font-size: 11.5px; color: var(--text-4);
  line-height: 1.65; max-width: 46ch; margin: 0;
}
.vn-tech { width: 100%; max-width: 430px; text-align: left; margin-top: 2px; }
.vn-tech summary {
  font-size: 11px; color: var(--text-4);
  cursor: pointer; text-align: center;
}
.vn-tech summary:hover { color: var(--text-2); }
.vn-tech pre {
  margin: 6px 0 0; padding: 8px 10px;
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; max-height: 92px; overflow: auto;
  font-family: var(--font-mono); font-size: 10.5px; line-height: 1.5;
  color: var(--text-4); white-space: pre-wrap; overflow-wrap: anywhere;
}

.vp-info {
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 6px;
}
.vi-row { display: flex; gap: 10px; font-size: 11.5px; align-items: baseline; }
.vi-k { color: var(--text-4); width: 56px; flex: none; }
.vi-v { color: var(--text-2); min-width: 0; word-break: break-all; }
.vi-acts {
  display: flex; gap: 6px; margin-top: 6px;
  padding-top: 10px; border-top: 1px dashed var(--line);
}
</style>
