<script setup>
/**
 * 统一页面导航条
 *
 * 全站统一：返回按钮 + 面包屑 + 右侧操作区。
 * 返回逻辑优先用浏览器历史，无历史时回落到首页。
 */
import BackButton from './BackButton.vue'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  title: { type: String, default: '' },
  sub: { type: String, default: '' },
  // [{ label, to }]  最后一项为当前页
  crumbs: { type: Array, default: () => [] },
  backTo: { type: String, default: '' }
})

const router = useRouter()

const items = computed(() => {
  if (props.crumbs.length) {
    const taskId = router.currentRoute.value.query.task
    if (taskId && props.crumbs.length === 2) {
      return [props.crumbs[0], { label: '任务 #' + taskId, to: '/tasks/' + taskId }, props.crumbs[1]]
    }
    return props.crumbs
  }
  return [{ label: '工作台', to: '/' }, { label: props.title }]
})
</script>

<template>
  <div class="pnav">
    <BackButton :fallback="backTo || items.at(-2)?.to || '/'" />

    <div class="heading">
    <nav class="crumbs" aria-label="面包屑">
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
    </div>

    <span class="spacer"></span>
    <div class="acts">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.pnav {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 0 22px;
  flex-wrap: wrap;
}
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

.heading { min-width: 0; }
.pnav-title { margin-top: 5px; }
.pnav-title .t {
  font-size: 22px; font-weight: 700;
  letter-spacing: -.4px; line-height: 1.25;
}
.pnav-title .s {
  font-size: 12px; color: var(--text-3);
  margin-top: 3px;
}
.spacer { flex: 1; }
.acts { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
@media (max-width: 720px) { .acts { flex-basis: 100%; } .pnav { align-items: flex-start; } }
</style>
