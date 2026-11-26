<script setup>
const size = defineModel({ type: Number, required: true })
const props = defineProps({
  label: { type: String, required: true },
  min: { type: Number, required: true },
  max: { type: Number, required: true },
  horizontal: Boolean
})
let drag
const clamp = value => Math.round(Math.max(props.min, Math.min(props.max, value)))
const coordinate = event => props.horizontal ? event.clientY : event.clientX

function start(event) {
  if (!event.isPrimary || event.button !== 0) return
  event.currentTarget.setPointerCapture(event.pointerId)
  drag = { start: coordinate(event), size: size.value }
}
function move(event) {
  if (drag && event.currentTarget.hasPointerCapture(event.pointerId)) {
    size.value = clamp(drag.size + coordinate(event) - drag.start)
  }
}
function keydown(event) {
  const decrease = props.horizontal ? 'ArrowUp' : 'ArrowLeft'
  const increase = props.horizontal ? 'ArrowDown' : 'ArrowRight'
  const values = { [decrease]: size.value - 12, [increase]: size.value + 12, Home: props.min, End: props.max }
  if (!Object.hasOwn(values, event.key)) return
  event.preventDefault()
  size.value = clamp(values[event.key])
}
</script>

<template>
  <div class="pane-divider" :class="{ horizontal }" role="separator" tabindex="0"
       :aria-label="label" :aria-orientation="horizontal ? 'horizontal' : 'vertical'"
       :aria-valuemin="min" :aria-valuemax="max" :aria-valuenow="size"
       @pointerdown="start" @pointermove="move" @lostpointercapture="drag = null"
       @keydown="keydown"></div>
</template>

<style scoped>
.pane-divider { display:grid; place-items:center; cursor:col-resize; touch-action:none; min-width:0; }
.pane-divider.horizontal { cursor:row-resize; }
.pane-divider::after { content:''; background:var(--line-2); width:2px; height:32px; border-radius:2px; }
.pane-divider.horizontal::after { width:32px; height:2px; }
.pane-divider:is(:hover,:focus-visible)::after { background:var(--brand); }
</style>
