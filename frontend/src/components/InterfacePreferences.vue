<script setup>
import { feedback, hapticsAvailable, preferences, setPreference } from '../stores/interface'
</script>

<template>
  <section class="card mb-16" aria-labelledby="appearance-title">
    <header class="card-head">
      <h2 id="appearance-title">界面与反馈</h2>
    </header>
    <div class="card-body preference-list">
      <div class="preference">
        <div><label for="material">面板样式</label><p>适用于浅色、深色和跟随系统。</p></div>
        <select id="material" class="inp" :value="preferences.material" @change="setPreference('material', $event.target.value)">
          <option value="clean">清晰</option><option value="glass">玻璃</option>
        </select>
      </div>
      <div class="preference">
        <div><label for="density">信息密度</label><p>调整表格行距与面板留白。</p></div>
        <select id="density" class="inp" :value="preferences.density" @change="setPreference('density', $event.target.value)">
          <option value="comfortable">舒展</option><option value="compact">紧凑</option>
        </select>
      </div>
      <div class="preference">
        <div><label for="sound">界面音效</label><p>为提交、完成和失败提供轻量声音提示。</p></div>
        <input id="sound" role="switch" type="checkbox" :checked="preferences.sound"
          @change="setPreference('sound', $event.target.checked); if (preferences.sound) feedback('confirm')" />
      </div>
      <div class="preference">
        <div>
          <label for="haptics">触感反馈</label>
          <p>{{ hapticsAvailable ? '支持的设备会在关键操作时短振。' : '当前设备使用按压动效反馈。' }}</p>
        </div>
        <input id="haptics" role="switch" type="checkbox" :disabled="!hapticsAvailable"
          :checked="preferences.haptics && hapticsAvailable" @change="setPreference('haptics', $event.target.checked); if (preferences.haptics) feedback('confirm')" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.card-head h2 { font-size:var(--text-size,14px); margin:0; }
.preference-list { padding-block:0; }
.preference {
  padding:var(--ui-row-y) 0;
  min-height:57px;
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:16px;
}
.preference + .preference { border-top:1px solid var(--line); }
.preference label { font-size:13px; font-weight:650; }
.preference p { margin:2px 0 0; font-size:12px; color:var(--text-3); }
.preference .inp { min-width:88px; }
.preference input[role=switch] {
  appearance:none;
  margin:0;
  flex:none;
  inline-size:36px; block-size:21px;
  display:grid; align-items:center;
  padding-inline:3px;
  border:1px solid var(--line-strong);
  border-radius:30px;
  background:var(--surface-3);
  cursor:pointer;
  transition:background-color 150ms var(--ease),border-color 150ms var(--ease);
}
.preference input[role=switch]::before {
  content:'';
  width:13px; height:13px;
  border-radius:50%;
  background:var(--text-2);
  transition:translate 150ms var(--ease);
}
.preference input[role=switch]:checked { background:var(--ds-dk); border-color:var(--ds-dk); }
.preference input[role=switch]:checked::before { translate:15px 0; background:white; }
.preference input[role=switch]:disabled { opacity:.55; cursor:default; }
</style>
