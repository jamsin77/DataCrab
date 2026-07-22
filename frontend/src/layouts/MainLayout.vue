<template>
  <el-container class="main-layout">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapsed ? '64px' : '220px'" class="sidebar">
      <div class="logo">
        <h1 v-if="!isCollapsed">DataCrab</h1>
        <h1 v-else>DC</h1>
      </div>
      <el-menu
        :default-active="currentRoute"
        :collapse="isCollapsed"
        router
        class="sidebar-menu"
      >
        <el-menu-item index="/chat">
          <el-icon><ChatDotRound /></el-icon>
          <template #title>对话</template>
        </el-menu-item>
        <!-- 数据源管理已移至「系统配置」 -->
        <!-- <el-menu-item index="/datasource">
          <el-icon><Connection /></el-icon>
          <template #title>数据源</template>
        </el-menu-item> -->
        <el-menu-item index="/operator">
          <el-icon><Operation /></el-icon>
          <template #title>算子</template>
        </el-menu-item>
        <el-menu-item index="/skill">
          <el-icon><MagicStick /></el-icon>
          <template #title>技能</template>
        </el-menu-item>
        <el-menu-item index="/pipeline">
          <el-icon><Share /></el-icon>
          <template #title>流程</template>
        </el-menu-item>
        <el-menu-item index="/schedule">
          <el-icon><Timer /></el-icon>
          <template #title>调度</template>
        </el-menu-item>
        <el-menu-item index="/knowledge">
          <el-icon><Collection /></el-icon>
          <template #title>知识库</template>
        </el-menu-item>
        <el-menu-item index="/metadata">
          <el-icon><Files /></el-icon>
          <template #title>元数据</template>
        </el-menu-item>
        <el-menu-item index="/config">
          <el-icon><Setting /></el-icon>
          <template #title>系统配置</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <el-button text @click="isCollapsed = !isCollapsed">
          <el-icon><Fold v-if="!isCollapsed" /><Expand v-else /></el-icon>
        </el-button>
      </div>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <span class="page-title">{{ pageTitle }}</span>
        </div>
        <div class="header-right">
          <el-dropdown @command="handleUserCommand">
            <span class="user-info">
              <el-avatar :size="32" :src="authStore.user?.avatar || undefined">
                {{ authStore.user?.display_name?.charAt(0) || 'U' }}
              </el-avatar>
              <span class="username">{{ authStore.user?.display_name || '用户' }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="main-content">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const isCollapsed = ref(false)

const currentRoute = computed(() => route.path)
const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    '/chat': '对话',
    '/datasource': '数据源管理',
    '/metadata': '元数据',
    '/knowledge': '知识库',
    '/skill': '技能',
    '/operator': '算子管理',
    '/pipeline': '流程管理',
    '/schedule': '调度管理',
    '/filelink': '文件链接',
    '/config': '系统配置',
  }
  if (route.path === '/config') {
    const tab = route.query.tab as string
    if (tab === 'model') return '系统配置 - 模型设置'
    if (tab === 'agent') return '系统配置 - 智能体设置'
    if (tab === 'datasource') return '系统配置 - 数据源管理'
  }
  return titles[route.path] || 'DataCrab'
})

async function handleUserCommand(command: string) {
  if (command === 'logout') {
    await authStore.logout()
    router.push('/login')
  }
}
</script>

<style lang="scss" scoped>
.main-layout {
  height: 100vh;
}

.sidebar {
  background: #fafafa;
  display: flex;
  flex-direction: column;
  transition: width 0.3s;
  border-right: 1px solid #e8e8e8;

  .logo {
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #303133;
    border-bottom: 1px solid #e8e8e8;
    h1 {
      margin: 0;
      font-size: 20px;
      font-weight: 600;
    }
  }

  .sidebar-menu {
    flex: 1;
    border-right: none;
    background: transparent;
  }

  .sidebar-footer {
    padding: 12px;
    text-align: center;
    border-top: 1px solid #e8e8e8;
  }
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e6e6e6;
  background: #fff;

  .page-title {
    font-size: 18px;
    font-weight: 500;
  }

  .user-info {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }
}

.main-content {
  background: #f5f5f5;
  overflow: auto;
}
</style>
