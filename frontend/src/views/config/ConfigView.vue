<template>
  <div class="config-container">
    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <el-tab-pane label="智能体设置" name="agent">
        <AgentConfigView />
      </el-tab-pane>
      <el-tab-pane label="模型设置" name="model">
        <ModelConfigView />
      </el-tab-pane>
      <el-tab-pane label="大模型对话" name="llm-chat">
        <LLMChatView />
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
import LLMChatView from './LLMChatView.vue'
import PermissionView from './PermissionView.vue'

const route = useRoute()
const router = useRouter()
const activeTab = ref('agent')

onMounted(() => {
  const tab = (route.query.tab as string) || 'agent'
  if (['agent', 'model', 'llm-chat', 'permission'].includes(tab)) {
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
