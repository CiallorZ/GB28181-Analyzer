<script setup>
/**
 * 统一页面导航条
 *
 * 全站统一：返回按钮 + 面包屑 + 右侧操作区。
 * 返回逻辑优先用浏览器历史，无历史时回落到首页。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  title: { type: String, default: '' },
  sub: { type: String, default: '' },
  // [{ label, to }]  最后一项为当前页
  crumbs: { type: Array, default: () => [] },
  backTo: { type: String, default: '/' }
})

const router = useRouter()

function goBack() {
  // 有历史就后退，否则回落到 backTo
  if (window.history.length > 2) router.back()
  else router.push(props.backTo)
}

const items = computed(() => {
  if (props.crumbs.length) return props.crumbs
  return [{ label: '工作台', to: '/' }, { label: props.title }]
})
</script>

<template>
  <div class="pnav">
    <button class="back" @click="goBack" title="返回上一级">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
        <line x1="19" y1="12" x2="5" y2="12"/>
        <polyline points="12 19 5 12 12 5"/>
      </svg>
    </button>

    <nav class="crumbs">
      <template v-for="(c, i) in items" :key="i">
        <router-link v-if="c.to && i < items.length - 1" :to="c.to" class="crumb">
          {{ c.label }}
        </router-link>
        <span v-else class="crumb cur">{{ c.label }}</span>
        <span v-if="i < items.length - 1" class="sep">/</span>
      </template>
    </nav>

    <div class="pnav-title" v-if="title">
      <h1 class="t">{{ title }}</h1>
      <div v-if="sub" class="s">{{ sub }}</div>
    </div>

    <span class="spacer"></span>
    <div class="acts">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.pnav {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 0 18px;
  flex-wrap: wrap;
}
.back {
  width: 32px; height: 32px; flex: none;
  border-radius: var(--radius-sm);
  background: var(--surface);
  border: 1px solid var(--line);
  color: var(--text-2);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--dur) var(--ease);
}
.back:hover {
  border-color: var(--line-strong);
  color: var(--text);
  background: var(--surface-2);
}
.back svg { width: 15px; height: 15px; }

.crumbs {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px;
}
.crumb {
  color: var(--text-3);
  transition: color var(--dur-xs);
}
a.crumb:hover { color: var(--text); text-decoration: none; }
.crumb.cur { color: var(--text); font-weight: 500; }
.sep { color: var(--text-4); font-size: 10px; }

.pnav-title { margin-left: 6px; }
.pnav-title .t {
  font-size: 18px; font-weight: 650;
  letter-spacing: -.4px; line-height: 1.25;
}
.pnav-title .s {
  font-size: 12px; color: var(--text-3);
  margin-top: 3px;
}
.spacer { flex: 1; }
.acts { display: flex; align-items: center; gap: 8px; }
</style>
