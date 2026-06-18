<template>
  <div class="flow-node" :style="{ borderColor: data.color }">
    <div class="flow-node-label" :style="{ color: data.color }">{{ data.label }}</div>
    <div v-if="data.sub" class="flow-node-sub">{{ data.sub }}</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  data: {
    label: string
    sub?: string
    color: string
  }
}>()
</script>

<style scoped>
.flow-node {
  background: #fff;
  border: 2px solid #409eff;
  border-radius: 10px;
  padding: 10px 18px;
  min-width: 160px;
  text-align: center;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  cursor: grab;
  transition: box-shadow 0.2s;
}
.flow-node:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
}
.flow-node-label {
  font-weight: 700;
  font-size: 14px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  white-space: nowrap;
}
.flow-node-sub {
  font-size: 11px;
  color: #909399;
  margin-top: 3px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}
</style>
