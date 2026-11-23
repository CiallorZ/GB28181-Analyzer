<script setup>
defineProps({ name: { type: String, required: true } })
const paths = {
  "warning": ["m10.5 4.5-8 14.2q-.7 1.7 1.5 1.7h16q2 0 1-2L13.2 4.5q-1.3-2.1-2.7 0z","M12 9v4m0 3v.3"],
  "down": ["m5 9 7 7 7-7",""],
  "signal": ["M4 3.8v16.4M20 3.8v16.4", "M7 8h10l-2.7-2.5M17 16H7l2.7 2.5"],
  "wave": ["M3 8.5v7m4-10v13m4-9v5m4-11v17m4-14v11", ""],
  "codec": ["M5 5h14v14H5zM8 2.5v2m4-2v2m4-2v2M8 19.5v2m4-2v2m4-2v2M2.5 8h2m-2 4h2m-2 4h2m15-8h2m-2 4h2m-2 4h2","m10 9 5 3-5 3z"],
  "home": [
    "M3 10.5 11 4a1.6 1.6 0 0 1 2 0l8 6.5 M5.5 10v9a1.5 1.5 0 0 0 1.5 1.5h10a1.5 1.5 0 0 0 1.5-1.5v-9",
    "M9 16h2l1.3-3 1.3 3H16"
  ],
  "history": [
    "M4 10a8.2 8.2 0 1 1 .8 6 M3.4 5.8v4.8h4.8",
    "M12 7.8v4.4l3.2 1.8"
  ],
  "compare": [
    "M3 7h14m-3-3 3 3-3 3 M21 17H7m3-3-3 3 3 3",
    "M4 14v5m16-14v5"
  ],
  "settings": [
    "M4 7h5m5 0h6M4 17h9m5 0h2",
    "M9 7a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0M13 17a2.5 2.5 0 1 0 5 0 2.5 2.5 0 1 0-5 0"
  ],
  "back": [
    "m11 5-7 7 7 7",
    "M5 12h15"
  ],
  "close": [
    "m6 6 12 12",
    "m18 6-12 12"
  ],
  "send": [
    "M3.5 10.3 20 3.8l-5.4 16.6-3.4-7.6z",
    "m11.3 12.8 5.2-5.2"
  ],
  "file": [
    "M6 3.5h8L19 9v10a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 6 19zM14 4v5h4",
    "M8.5 15h2l1.2-2.7 1.6 4.2 1.4-2h1.6"
  ],
  "upload": [
    "M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15",
    "M12 15V4m-4.2 4.2L12 4l4.2 4.2"
  ],
  "play": [
    "M7 5.8q0-1.7 1.5-.8l11 6.2q1.4.8 0 1.6l-11 6.2Q7 20 7 18.2z",
    ""
  ],
  "monitor": [
    "M4 4.5h16a1 1 0 0 1 1 1v11H3v-11a1 1 0 0 1 1-1zM8 20h8m-4-3v3",
    "m6 11 2.5 0 2-3 2.2 5 2-3h2.6"
  ],
  "storage": [
    "M4 6c0-4 16-4 16 0s-16 4-16 0zm0 0v12c0 4 16 4 16 0V6",
    "M4 12c0 4 16 4 16 0"
  ],
  "next": [
    "m9 5 7 7-7 7",
    ""
  ],
  "prev": [
    "m15 5-7 7 7 7",
    ""
  ],
  "open": [
    "M5 18 18 5",
    "M9.5 5H18v8.5"
  ],
  "forward": [
    "M4 12h15",
    "m13 6 6 6-6 6"
  ],
  "plus": [
    "M5 12h14",
    "M12 5v14"
  ],
  "minus": [
    "M5 12h14",
    ""
  ]
}
</script>
<template>
  <svg class="app-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path :d="paths[name][0]" />
    <path v-if="paths[name][1]" :d="paths[name][1]" />
  </svg>
</template>
<style scoped>
.app-icon { display:inline-block; width:1.15em; height:1.15em; flex:none; vertical-align:-.18em; }
</style>
