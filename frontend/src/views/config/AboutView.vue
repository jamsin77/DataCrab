<template>
  <div class="about-view">
    <div class="about-card">
      <div class="about-header">
        <div class="about-logo">
          <el-icon :size="56" color="#409EFF"><Platform /></el-icon>
        </div>
        <h1 class="about-title">DataCrab</h1>
        <p class="about-subtitle">数据工程智能体</p>
        <el-tag type="primary" effect="plain" round>v{{ version || '...' }}</el-tag>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">项目简介</h2>
        <p class="section-text">
          DataCrab 是一个 ChatGPT 风格的对话式数据工程智能体。用户通过自然语言对话即可完成数据查询、清洗、转换、分析、可视化——无需编写代码。
        </p>
        <p class="section-text">
          系统采用多智能体架构（DataProcessor + DataInspector），内置自愈循环：AI 理解需求 → 执行 → 检查 → 自修复，全程无人干预。支持多种数据源（PostgreSQL / MySQL / SQLite / CSV / Excel / OBS / HDFS / ChromaDB），集成大模型推理、技能脚本沙箱、流程编排、定时调度等能力。
        </p>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">核心特性</h2>
        <ul class="feature-list">
          <li><el-icon color="#67C23A"><Check /></el-icon> 对话式数据工程，零代码完成数据处理全流程</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 多智能体架构，自动检查与自愈修复循环</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 8 种数据源连接器，覆盖关系型数据库与文件格式</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 技能 / 算子 / 流程三层编排，可跨机器迁移打包</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 确定性数据质量检查（标准 / 完整性 / 唯一性 / 安全）</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 定时调度系统，支持 cron 表达式与并发控制</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 视频处理能力（关键帧抽取 + 元数据提取）</li>
        </ul>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">技术栈</h2>
        <div class="tech-tags">
          <el-tag effect="plain">Python 3.11+</el-tag>
          <el-tag effect="plain" type="success">FastAPI</el-tag>
          <el-tag effect="plain" type="success">SQLAlchemy 2.0 async</el-tag>
          <el-tag effect="plain" type="success">pandas</el-tag>
          <el-tag effect="plain" type="warning">Vue 3 + TypeScript</el-tag>
          <el-tag effect="plain" type="warning">Vite 5</el-tag>
          <el-tag effect="plain" type="warning">Element Plus</el-tag>
          <el-tag effect="plain" type="warning">ECharts</el-tag>
          <el-tag effect="plain" type="danger">PostgreSQL</el-tag>
          <el-tag effect="plain" type="danger">SQLite</el-tag>
          <el-tag effect="plain" type="info">ChromaDB</el-tag>
          <el-tag effect="plain" type="info">GLM / Qwen / SiliconFlow</el-tag>
        </div>
      </div>

      <el-divider />

      <div class="about-section about-footer">
        <div class="footer-row">
          <span class="footer-label">开源地址：</span>
          <el-link type="primary" :underline="false" @click="openLink">
            https://gitee.com/DataCrab/DataCrab
            <el-icon class="link-icon"><Link /></el-icon>
          </el-link>
        </div>
        <p class="footer-copy">© 2026 DataCrab · 开源协作，共同进步</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Platform, Check, Link } from '@element-plus/icons-vue'
import { useVersionStore } from '@/stores/version'

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
