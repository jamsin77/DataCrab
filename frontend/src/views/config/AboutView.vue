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
          DataCrab 是一款基于大语言模型（LLM）的数据工程智能体，提供 ChatGPT 风格的对话式数据交互体验。用户无需编写代码，通过自然语言对话即可完成数据的查询、清洗、转换、分析和可视化等操作。
        </p>
        <p class="section-text">
          系统采用 <b>Orchestrator-Worker</b> 多智能体协作架构（参考 Claude Code / OpenAI Agents SDK）：DataProcessor 负责修改与执行，DataInspector 负责质量/标准/安全检查，DataAnalyst 承担只读分析。Handoff 由 RunTime 自动决策，Agent 不感知交接存在。内置自愈循环——AI 理解需求 → 执行 → 检查 → 自修复，全程无人干预，逐步迈向「Loop 化」终极目标。
        </p>
        <p class="section-text">
          核心理念：<b>对话即处理 → 沉淀即资产 → 生态即闭环 → Loop 化</b>。AI 在「执行 → 观测 → 修正」的循环中持续迭代，直到任务完成；每次处理过程自动沉淀为可复用技能，越用越聪明。
        </p>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">核心特性</h2>
        <ul class="feature-list">
          <li><el-icon color="#67C23A"><Check /></el-icon> 对话式数据工程，零代码完成查询/清洗/转换/分析/可视化全流程</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 三智能体协作闭环：DataProcessor 加工 + DataInspector 检查 + DataAnalyst 只读分析，Handoff 由 RunTime 自动决策</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> AI 调试助手：4 工具模型（edit_script/run_script/read_script/grep_script，对齐 OpenCode Grep/Read/Edit/Bash），AI 修改脚本后自动执行验证</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 自我进化经验库：失败记录反例、修错后成功采集正例，LLM 归纳经验注入后续生成/修改/调试提示词</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 8 种数据源连接器：PostgreSQL / MySQL / SQLite / CSV / Excel / OBS-S3 / HDFS / ChromaDB；写入支持 7 种策略（fail/append/replace/overwrite/truncate/delete_rows/upsert）</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 技能 / 算子 / 流程三层编排，资产打包可跨机器迁移；流程 = Python 主函数，无需 DAG 引擎</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 31 条确定性数据检查（STD 标准 / DQ 质量 / SEC 安全），Markdown 规则库可编辑，检查报告表格化展示</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 定时调度系统：支持 Cron 表达式 / 固定间隔 / 手动触发，后台实际执行 + 并发控制</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 文档知识库 RAG：上传文档自动切片嵌入 ChromaDB，语义检索注入 Agent 提示词</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> RBAC 权限体系：用户 → 角色 → 权限（view/use/manage 三级），资源级访问控制</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> LLM 多模型支持：GLM / Qwen / SiliconFlow / Azure / 自定义 OpenAI 兼容；双模型架构 + 降级链 + CircuitBreaker 熔断；视觉/嵌入模型按 provider 自动选择</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 自定义数据源连接器 + LLM Provider 适配器：AI 生成代码，沙箱加载，用户自助扩展</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> 视频处理能力：关键帧抽取 + 元数据提取（ffmpeg 场景检测优先，回退 opencv）</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> Prefix Cache 优化：system prompt 字节稳定命中 GLM context cache，input 成本降 30%+；上下文压缩（Compaction）对齐 OpenCode</li>
          <li><el-icon color="#67C23A"><Check /></el-icon> Docker 一键部署：前端多阶段构建 nginx 托管 + SSE 长连接支持 + 数据卷持久化</li>
        </ul>
      </div>

      <el-divider />

      <div class="about-section">
        <h2 class="section-title">技术栈</h2>
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
          <el-tag effect="plain" type="info">GLM / Qwen / SiliconFlow / Azure / 自定义</el-tag>
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
