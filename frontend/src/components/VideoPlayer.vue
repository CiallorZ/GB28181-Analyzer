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
    ok: !!rb.ok && !!s.rebuilt_path,
    aligned: !!rb.aligned,
    duration: rb.duration ?? s.duration,
    psBytes: rb.ps_bytes,
    error: rb.error || s.rebuild_error,
    codec: s.codec,
    width: s.width,
    height: s.height,
    fps: s.fps,
    frames: s.frame_count
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
  a.download = `stream-${props.stream.ssrc ? props.stream.ssrc.toString(16) : props.stream.id}.mp4`
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
            {{ info.width }}×{{ info.height }}
            <template v-if="info.fps"> · {{ info.fps }}fps</template>
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
        <div class="vn-reason">{{ info.error || '该流没有可解码的视频载荷' }}</div>
      </div>
    </div>

    <!-- 信息栏 -->
    <div class="vp-info">
      <div class="vi-row">
        <span class="vi-k">SSRC</span>
        <span class="vi-v mono">0x{{ stream.ssrc?.toString(16) }}</span>
      </div>
      <div class="vi-row">
        <span class="vi-k">传输</span>
        <span class="vi-v">{{ stream.transport }} · {{ stream.source_port }} → {{ stream.destination_port }}</span>
      </div>
      <template v-if="info.ok">
        <div class="vi-row">
          <span class="vi-k">编码</span>
          <span class="vi-v">
            <span class="badge brand">{{ info.codec || '未知' }}</span>
          </span>
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
  transition: all var(--dur) var(--ease);
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
  object-fit: cover;
  opacity: .82;
  transition: opacity var(--dur) var(--ease), transform var(--dur-lg) var(--ease);
}
.vp-cover:hover .vp-poster {
  opacity: 1;
  transform: scale(1.03);
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
  gap: 10px; padding: 24px;
  background: var(--surface);
  text-align: center;
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
.vn-reason {
  font-size: 11px; color: var(--text-4);
  line-height: 1.65; max-width: 320px;
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
