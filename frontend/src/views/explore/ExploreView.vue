<template>
  <div class="explore-container">
    <div class="explore-sidebar">
      <h3>数据源</h3>
      <el-tree :data="treeData" :props="{ label: 'label', children: 'children' }" @node-click="handleNodeClick" />
    </div>
    <div class="explore-main">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="数据预览" name="preview">
          <el-table :data="tableData" stripe max-height="500" />
        </el-tab-pane>
        <el-tab-pane label="统计信息" name="stats">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="行数">{{ stats.rowCount }}</el-descriptions-item>
            <el-descriptions-item label="列数">{{ stats.columnCount }}</el-descriptions-item>
            <el-descriptions-item label="大小">{{ stats.sizeBytes }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="数据质量" name="quality">
          <div class="quality-charts">
            <div ref="completenessChartRef" class="chart-item"></div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="分布分析" name="distribution">
          <div ref="distributionChartRef" class="chart-item"></div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const treeData = ref<any[]>([])
const tableData = ref<any[]>([])
const activeTab = ref('preview')
const stats = ref({ rowCount: 0, columnCount: 0, sizeBytes: 0 })
const completenessChartRef = ref<HTMLElement>()
const distributionChartRef = ref<HTMLElement>()

function handleNodeClick(data: any) {
  // TODO: 加载选中节点的数据
}
</script>

<style lang="scss" scoped>
.explore-container {
  display: flex;
  height: 100%;
  gap: 16px;
}

.explore-sidebar {
  width: 280px;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow-y: auto;

  h3 { margin: 0 0 12px; }
}

.explore-main {
  flex: 1;
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow-y: auto;
}

.chart-item {
  height: 400px;
}
</style>
