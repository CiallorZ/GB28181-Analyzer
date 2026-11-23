<script setup>
import { useRouter } from 'vue-router'
const props = defineProps({ fallback: { type: String, default: '/' } })
const router = useRouter()
function goBack() {
  if (router.options.history.state.back) router.back()
  else router.replace(props.fallback)
}
</script>
<template>
  <button type="button" class="btn back-button" title="返回上一页" aria-label="返回上一页" @click="goBack">
    <AppIcon name="back" />
  </button>
</template>
<style scoped>
.back-button { width:32px; height:32px; padding:0; flex:none; }
</style>
