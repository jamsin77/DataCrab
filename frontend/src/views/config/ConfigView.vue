<template>
  <div class="config-container">
    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <el-tab-pane label="性格设定管理" name="agent">
        <AgentConfigView />
      </el-tab-pane>
      <el-tab-pane label="数据源管理" name="datasource">
        <DataSourceView />
      </el-tab-pane>
      <el-tab-pane label="大模型管理" name="model">
        <ModelConfigView />
      </el-tab-pane>
      <el-tab-pane label="数据规则管理" name="standards">
        <DataStandardsConfig />
      </el-tab-pane>
      <el-tab-pane label="元数据管理" name="metadata">
        <MetadataView />
      </el-tab-pane>
      <el-tab-pane label="权限管理" name="permission">
        <PermissionView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AgentConfigView from './AgentConfigView.vue'
import ModelConfigView from './ModelConfigView.vue'
import DataStandardsConfig from './DataStandardsConfig.vue'
import PermissionView from './PermissionView.vue'
import MetadataView from '@/views/metadata/MetadataView.vue'
import DataSourceView from '@/views/datasource/DataSourceView.vue'

const route = useRoute()
const router = useRouter()
const activeTab = ref('agent')

onMounted(() => {
  const tab = (route.query.tab as string) || 'agent'
  if (['datasource', 'agent', 'model', 'standards', 'metadata', 'permission'].includes(tab)) {
    activeTab.value = tab
  }
})

function handleTabChange(tab: string) {
  router.replace({ path: '/config', query: { tab } })
}
</script>

<style lang="scss" scoped>
.config-container {
  padding: 20px;

  :deep(.el-tabs__header) {
    margin-bottom: 20px;
  }
}
</style>
