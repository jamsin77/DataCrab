<template>
  <div class="about-view">
    <div class="about-card">
      <div class="about-header">
        <div class="about-logo">
          <el-icon :size="56" color="#409EFF"><Platform /></el-icon>
        </div>
        <h1 class="about-title">{{ t('config.about.projectName') }}</h1>
        <p class="about-subtitle">{{ t('config.about.subtitle') }}</p>
        <el-tag type="primary" effect="plain" round>v{{ version || '...' }}</el-tag>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">{{ t('config.about.intro') }}</h2>
        <p class="section-text">
          {{ t('config.about.introP1') }}
        </p>
        <p class="section-text">
          {{ t('config.about.introP2') }}
        </p>
        <p class="section-text">
          {{ t('config.about.introP3') }}
        </p>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">{{ t('config.about.features') }}</h2>
        <ul class="feature-list">
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat1') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat2') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat3') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat4') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat5') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat6') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat7') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat8') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat9') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat10') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat11') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat12') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat13') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat14') }}</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> {{ t('config.about.feat15') }}</li>
        </ul>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">{{ t('config.about.techStack') }}</h2>
        <div class="tech-tags">
          <el-tag effect="plain">Python 3.11+</el-tag>
          <el-tag effect="plain" type="success">FastAPI + Uvicorn</el-tag>
          <el-tag effect="plain" type="success">SQLAlchemy 2.0 async</el-tag>
          <el-tag effect="plain" type="success">pandas / numpy</el-tag>
          <el-tag effect="plain" type="warning">Vue 3 + TypeScript</el-tag>
          <el-tag effect="plain" type="warning">Vite 5</el-tag>
          <el-tag effect="plain" type="warning">Element Plus</el-tag>
          <el-tag effect="plain" type="warning">Pinia / Vue Router 4</el-tag>
          <el-tag effect="plain" type="warning">ECharts 5</el-tag>
          <el-tag effect="plain" type="warning">Monaco Editor</el-tag>
          <el-tag effect="plain" type="warning">Vue Flow</el-tag>
          <el-tag effect="plain" type="warning">markdown-it + highlight.js</el-tag>
          <el-tag effect="plain" type="danger">PostgreSQL 14+</el-tag>
          <el-tag effect="plain" type="danger">SQLite</el-tag>
          <el-tag effect="plain" type="info">ChromaDB</el-tag>
          <el-tag effect="plain" type="info">GLM / Qwen / SiliconFlow / Azure / {{ t('config.about.custom') }}</el-tag>
        </div>
      </div>

      <el-divider />

      <div class="about-section about-footer">
        <div class="footer-row">
          <span class="footer-label">{{ t('config.about.openSource') }}：</span>
          <el-link type="primary" :underline="false" @click="openLink">
            https://gitee.com/DataCrab/DataCrab
            <el-icon class="link-icon"><Link /></el-icon>
          </el-link>
        </div>
        <p class="footer-copy">{{ t('config.about.copyright') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Platform, Check, Link } from '@element-plus/icons-vue'
import { useVersionStore } from '@/stores/version'

const { t } = useI18n()
const versionStore = useVersionStore()
const version = ref('')

onMounted(async () => {
  version.value = await versionStore.loadVersion()
})

function openLink() {
  window.open('https://gitee.com/DataCrab/DataCrab', '_blank')
}
</script>

<style lang="scss" scoped>
.about-view {
  max-width: 820px;
  margin: 0 auto;
}

.about-card {
  background: var(--el-bg-color);
  border-radius: 12px;
  padding: 40px 48px;
  box-shadow: 0 2px 16px rgba(0, 0, 0, 0.06);
}

.about-header {
  text-align: center;
  padding: 16px 0 8px;
}

.about-logo {
  margin-bottom: 12px;
}

.about-title {
  font-size: 32px;
  font-weight: 700;
  margin: 0;
  color: var(--el-text-color-primary);
  letter-spacing: 1px;
}

.about-subtitle {
  font-size: 15px;
  color: var(--el-text-color-secondary);
  margin: 6px 0 12px;
}

.about-section {
  .section-title {
    font-size: 17px;
    font-weight: 600;
    margin: 0 0 14px;
    color: var(--el-text-color-primary);
    padding-left: 10px;
    border-left: 3px solid var(--el-color-primary);
  }

  .section-text {
    font-size: 14px;
    line-height: 1.85;
    color: var(--el-text-color-regular);
    margin: 0 0 10px;
    text-align: justify;
  }
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;

  li {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--el-text-color-regular);
    padding: 7px 0;
  }
}

.tech-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.about-footer {
  text-align: center;
}

.footer-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  font-size: 15px;
  margin-bottom: 12px;

  .footer-label {
    color: var(--el-text-color-secondary);
  }

  .link-icon {
    margin-left: 4px;
    vertical-align: -2px;
  }
}

.footer-copy {
  font-size: 13px;
  color: var(--el-text-color-placeholder);
  margin: 0;
}
</style>
