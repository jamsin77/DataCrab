<template>
  <div class="config-container">
    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <el-tab-pane :label="t('layout.configTabs.agent')" name="agent">
        <AgentConfigView />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.datasource')" name="datasource">
        <DataSourceView />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.model')" name="model">
        <ModelConfigView />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.standards')" name="standards">
        <DataStandardsConfig />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.metadata')" name="metadata">
        <MetadataView />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.permission')" name="permission">
        <PermissionView />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.asset')" name="assets">
        <AssetManagerView />
      </el-tab-pane>
      <el-tab-pane :label="t('layout.configTabs.about')" name="about">
        <AboutView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import AgentConfigView from './AgentConfigView.vue'
import ModelConfigView from './ModelConfigView.vue'
import DataStandardsConfig from './DataStandardsConfig.vue'
import PermissionView from './PermissionView.vue'
import AssetManagerView from './AssetManagerView.vue'
import AboutView from './AboutView.vue'
import MetadataView from '@/views/metadata/MetadataView.vue'
import DataSourceView from '@/views/datasource/DataSourceView.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const activeTab = ref('agent')

onMounted(() => {
  const tab = (route.query.tab as string) || 'agent'
  if (['datasource', 'agent', 'model', 'standards', 'metadata', 'permission', 'assets', 'about'].includes(tab)) {
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
