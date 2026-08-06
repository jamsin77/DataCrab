<template>
  <div class="skill-page">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="success" @click="showGenerateDialog = true">
          <el-icon><MagicStick /></el-icon>
          生成技能
        </el-button>
        <el-button type="primary" @click="showUploadDialog = true">
          <el-icon><Upload /></el-icon>
          导入技能
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-select v-model="sortBy" style="width: 120px" @change="loadSkills">
          <el-option label="创建时间" value="created" />
          <el-option label="修改时间" value="updated" />
        </el-select>
        <el-select v-model="filterCategory" placeholder="分类筛选" clearable style="width: 140px">
          <el-option v-for="cat in categories" :key="cat" :label="cat" :value="cat" />
        </el-select>
        <el-input
          v-model="searchQuery"
          placeholder="搜索技能"
          style="width: 220px"
          clearable
          :prefix-icon="Search"
        />
      </div>
    </div>

    <div class="op-grid">
      <el-card v-for="skill in filteredSkills" :key="skill.id" class="skill-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <span class="skill-name">{{ skill.display_name || skill.name }}</span>
            <el-tag size="small" :type="categoryColor(skill.category)">{{ skill.category || '未分类' }}</el-tag>
          </div>
        </template>
        <p class="skill-desc">{{ skill.description || '暂无描述' }}</p>

        <div class="skill-meta">
          <el-tag v-if="skill.scripts?.length" size="small" effect="plain">
            {{ skill.scripts.length }} 个脚本
          </el-tag>
          <el-tag v-if="skill.version" size="small" effect="plain">v{{ skill.version }}</el-tag>
        </div>

        <div class="skill-actions">
          <div class="skill-actions-row">
            <el-button size="small" type="primary" @click="openDetail(skill)">
              <el-icon><Edit /></el-icon> 修改
            </el-button>
            <el-button size="small" type="success" plain @click="openDebug(skill)">
              <el-icon><VideoPlay /></el-icon> 调试
            </el-button>
            <el-button size="small" @click="openCloneDialog(skill)">
              <el-icon><CopyDocument /></el-icon> 另存
            </el-button>
            <el-button size="small" @click="downloadSkill(skill)">
              <el-icon><Download /></el-icon> 下载
            </el-button>
            <el-button size="small" type="danger" plain @click="confirmDelete(skill)">
              <el-icon><Delete /></el-icon> 删除
            </el-button>
          </div>
        </div>
      </el-card>
    </div>

    <el-empty v-if="filteredSkills.length === 0" description="暂无技能，请导入 SKILL 包" />

    <!-- ==================== 另存为对话框 ==================== -->
    <el-dialog v-model="showCloneDialog" title="另存为" width="450px" @closed="cloneName = ''; cloneTarget = null">
      <div v-if="cloneTarget" class="modify-target-info">
        <el-tag>{{ cloneTarget.display_name || cloneTarget.name }}</el-tag>
        <span class="modify-desc">将复制脚本和全部配置</span>
      </div>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item label="新名称" required>
          <el-input
            v-model="cloneName"
            placeholder="输入新技能的名称"
            @keyup.enter="handleClone"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCloneDialog = false">取消</el-button>
        <el-button type="primary" @click="handleClone" :loading="cloning" :disabled="!cloneName.trim()">
          {{ cloning ? '复制中...' : '确认复制' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== 导入对话框 ==================== -->
    <el-dialog v-model="showUploadDialog" title="导入技能" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          请上传 .zip 格式的技能包，包内需包含 SKILL.md 文件。同名技能可选择覆盖或重命名
        </template>
      </el-alert>
      <el-upload
        drag
        :show-file-list="false"
        :before-upload="validateZip"
        :http-request="handleUploadZip"
        accept=".zip"
      >
        <el-icon style="font-size: 48px"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽或点击上传 .zip 文件</div>
      </el-upload>
      <template #footer>
        <el-button @click="showUploadDialog = false">取消</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 重名冲突对话框 ==================== -->
    <el-dialog v-model="showConflictDialog" title="技能已存在" width="460px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom:16px">
        <template #title>
          技能 "{{ conflictInfo?.parsed_name }}" 已存在，请选择覆盖或重命名
        </template>
      </el-alert>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item label="新名称">
          <el-input
            v-model="renameValue"
            placeholder="输入新技能名称"
            @keyup.enter="confirmRename"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showConflictDialog = false">取消</el-button>
        <el-button type="danger" plain :loading="importing" @click="confirmOverwrite">覆盖原有</el-button>
        <el-button type="primary" :loading="importing" @click="confirmRename">重命名导入</el-button>
      </template>
    </el-dialog>

    <!-- ==================== AI 生成对话框 ==================== -->
    <el-dialog v-model="showGenerateDialog" title="AI 生成技能" width="95%" top="2vh" :close-on-press-escape="false" @closed="onGenerateDialogClosed">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          Skill Creator 将根据需求描述生成完整 Skill 包（SKILL.md + 脚本）
        </template>
      </el-alert>
      <el-form label-width="80px">
        <el-form-item label="需求描述">
          <el-input
            v-model="generatePrompt"
            type="textarea"
            :rows="5"
            placeholder="用自然语言描述你需要什么技能，例如：按照年代筛选文物数据，支持根据数据源名称查询，返回前100条"
            :disabled="generating"
            @keydown="onGenHistoryKey"
          />
          <div class="history-tip" v-if="genHistory.length && !generating">
            ↑↓ 切换历史输入（共 {{ genHistory.length }} 条）
          </div>
        </el-form-item>
      </el-form>

      <div v-if="genMessages.length" class="gen-msg-list" ref="genMsgListRef">
        <div v-for="(msg, idx) in genMessages" :key="idx" class="debug-message" :class="msg.role">
          <div class="debug-msg-avatar">
            <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
            <el-avatar :size="32" v-else style="background:#67c23a">我</el-avatar>
          </div>
          <div class="debug-msg-body">
            <div v-if="msg.role === 'user'" class="debug-msg-user">{{ msg.content }}</div>
            <div v-else class="debug-msg-assistant">
              <div v-if="msg.thinking" class="debug-msg-thinking">
                <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                  <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                  <span>推理过程<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
                </div>
                <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
              </div>
              <div v-if="msg.content" class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div v-if="generating && idx === genMessages.length - 1 && !msg.content && !msg.thinking" class="typing-indicator"><span></span><span></span><span></span></div>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <el-button @click="showGenerateDialog = false" :disabled="generating">取消</el-button>
        <el-button v-if="generating" type="danger" @click="stopGenerate">
          <el-icon><VideoPause /></el-icon> 停止
        </el-button>
        <el-button type="primary" @click="handleGenerate" :loading="generating || checkingSimilar" :disabled="generating || checkingSimilar">
          {{ generating ? 'AI 生成中...' : (checkingSimilar ? '检测相似技能...' : '开始生成') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== 相似技能检测对话框 ==================== -->
    <el-dialog v-model="showSimilarDialog" title="发现相似技能" width="600px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        <template #title>以下技能可能与您的需求相似，建议优先复用：</template>
      </el-alert>

      <div v-for="skill in similarSkills" :key="skill.id" class="similar-skill-item">
        <div class="similar-skill-header">
          <span class="similar-skill-name">{{ skill.display_name || skill.name }}</span>
          <el-tag v-if="skill.category" size="small">{{ skill.category }}</el-tag>
          <span class="similar-skill-score">相似度 {{ (skill.similarity * 100).toFixed(0) }}%</span>
        </div>
        <div class="similar-skill-desc">{{ skill.description || '(无描述)' }}</div>

        <div v-if="skill.can_use" class="similar-skill-actions">
          <el-button type="primary" size="small" @click="openExistingSkill(skill)">查看此技能</el-button>
        </div>
        <div v-else class="similar-skill-contact">
          <el-alert type="info" :closable="false">
            <template #title>
              您无权限使用此技能，请联系创建者：{{ skill.owner_name }}（{{ skill.owner_email }}）
            </template>
          </el-alert>
        </div>
      </div>

      <template #footer>
        <el-button @click="showSimilarDialog = false">取消</el-button>
        <el-button type="primary" @click="proceedToGenerate">仍然创建新技能</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 技能详情/修改 Drawer ==================== -->
    <el-dialog
      v-model="detailDrawer"
      :title="detailSkill?.display_name || detailSkill?.name || '技能详情'"
      width="95%"
      top="2vh"
      destroy-on-close
      :close-on-press-escape="false"
      class="detail-dialog"
    >
      <div v-if="detailSkill" class="detail-container">
        <div class="nl-modify-section">
          <div class="nl-modify-header">
            <span class="nl-modify-title">自然语言修改</span>
            <span class="nl-modify-hint">用自然语言描述你想如何修改这个技能</span>
          </div>
          <div class="nl-modify-input-row">
            <el-input
              v-model="modifyInstruction"
              type="textarea"
              :rows="2"
              placeholder="例如：把描述改成更专业的风格，添加使用示例，修改分类为数据处理（↑↓ 切换历史输入）"
              class="nl-modify-input"
              @keydown="onModifyHistoryKey"
            />
            <el-button
              v-if="!modifying"
              type="primary"
              @click="handleModifySkill"
              :disabled="!modifyInstruction.trim()"
            >
              <el-icon><MagicStick /></el-icon>
              AI 修改
            </el-button>
            <el-button
              v-else
              type="danger"
              @click="modifyAbortCtrl?.abort()"
            >
              <el-icon><VideoPause /></el-icon>
              停止
            </el-button>
          </div>
          <div v-if="modifyError" class="modify-error">
            <el-alert :title="modifyError" type="error" show-icon :closable="false" />
          </div>
          <div v-if="modifyMessages.length" class="gen-msg-list">
            <div v-for="(msg, idx) in modifyMessages" :key="idx" class="debug-message" :class="msg.role">
              <div class="debug-msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
                <el-avatar :size="32" v-else style="background:#67c23a">我</el-avatar>
              </div>
              <div class="debug-msg-body">
                <div v-if="msg.role === 'user'" class="debug-msg-user">{{ msg.content }}</div>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>推理过程</span>
                    </div>
                    <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
                  </div>
                  <div v-if="msg.content" class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                  <div v-if="modifying && idx === modifyMessages.length - 1 && !msg.content && !msg.thinking" class="typing-indicator"><span></span><span></span><span></span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <el-divider />

        <div class="detail-preview-label">技能详情预览</div>

        <el-tabs v-model="detailTab" class="detail-tabs">
          <el-tab-pane label="SKILL.md" name="md">
            <div class="md-editor-toolbar">
              <el-radio-group v-model="mdMode" size="small">
                <el-radio-button value="preview">预览</el-radio-button>
                <el-radio-button value="edit">编辑</el-radio-button>
              </el-radio-group>
              <el-button size="small" type="primary" :loading="savingMd" @click="saveSkillMd">
                <el-icon><Check /></el-icon> 保存
              </el-button>
            </div>
            <el-input
              v-if="mdMode === 'edit'"
              v-model="mdEditContent"
              type="textarea"
              :autosize="{ minRows: 12, maxRows: 30 }"
              placeholder="编辑 SKILL.md 内容（Markdown）"
              style="font-family: 'Consolas', 'Monaco', monospace; font-size: 13px"
            />
            <template v-else>
              <div v-if="mdEditContent" class="markdown-body" v-html="renderMarkdown(mdEditContent)"></div>
              <el-empty v-else description="暂无 SKILL.md 内容" />
            </template>
          </el-tab-pane>

          <el-tab-pane label="脚本列表" name="scripts">
            <div class="scripts-header">
              <span>{{ detailSkill.scripts?.length || 0 }} 个脚本</span>
            </div>
            <div v-if="detailSkill.scripts?.length" class="scripts-list">
              <div
                v-for="script in detailSkill.scripts"
                :key="script.name"
                class="script-item"
              >
                <div class="script-item-header" @click="toggleScript(script.name)">
                  <el-icon><component :is="expandedScript === script.name ? 'CaretBottom' : 'CaretRight'" /></el-icon>
                  <span class="script-name">{{ script.name }}</span>
                  <span class="script-size">{{ script.size ? (script.size / 1024).toFixed(1) + ' KB' : '' }}</span>
                </div>
                <div v-if="expandedScript === script.name" class="script-body">
                  <textarea
                    v-model="scriptContents[script.name]"
                    class="script-editor"
                    spellcheck="false"
                  ></textarea>
                  <div class="script-actions">
                    <el-button size="small" type="primary" @click="saveScriptContent(script.name)" :loading="savingScript">
                      <el-icon><Check /></el-icon> 保存
                    </el-button>
                    <el-button size="small" type="success" @click="openDebug(detailSkill, script.name)">
                      <el-icon><VideoPlay /></el-icon> 调试
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else description="暂无脚本" />
          </el-tab-pane>

          <el-tab-pane label="属性" name="props">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="名称">{{ detailSkill.name }}</el-descriptions-item>
              <el-descriptions-item label="显示名">{{ detailSkill.display_name }}</el-descriptions-item>
              <el-descriptions-item label="分类">
                <el-tag size="small" :type="categoryColor(detailSkill.category)">{{ detailSkill.category || '-' }}</el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="版本">v{{ detailSkill.version }}</el-descriptions-item>
              <el-descriptions-item label="可见性">{{ detailSkill.visibility }}</el-descriptions-item>
              <el-descriptions-item label="使用次数">{{ detailSkill.usage_count }}</el-descriptions-item>
              <el-descriptions-item label="存储路径" :span="2">
                <code>{{ detailSkill.skill_path }}</code>
              </el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ detailSkill.description || '-' }}</el-descriptions-item>
              <el-descriptions-item label="标签" :span="2">
                <el-tag v-for="tag in (detailSkill.tags || [])" :key="tag" size="small" style="margin-right:4px">{{ tag }}</el-tag>
                <span v-if="!detailSkill.tags?.length">-</span>
              </el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatDate(detailSkill.created_at) }}</el-descriptions-item>
              <el-descriptions-item label="更新时间">{{ formatDate(detailSkill.updated_at) }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <!-- ==================== 调试技能 Dialog ==================== -->
    <el-dialog
      v-model="debugDrawer"
      :title="'AI调试助手: ' + (debugSkill?.display_name || debugSkill?.name || '')"
      width="95%"
      top="2vh"
      destroy-on-close
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :before-close="handleDebugBeforeClose"
      @closed="resetDebug"
    >
      <div v-if="debugSkill" class="debug-layout">
        <div class="debug-left">
          <div class="debug-section-title"><span>执行参数</span></div>
          <el-tabs v-model="execTab">
            <el-tab-pane label="自然语言" name="nl">
              <div v-if="nlExamples.length" class="nl-examples">
                <div class="nl-examples-title">示例</div>
                <div v-for="(ex, i) in nlExamples" :key="i" class="nl-example-item" @click="execNLQuery = ex">
                  <span class="nl-example-text">{{ ex }}</span>
                </div>
              </div>
              <div class="nl-hint" v-if="nlHint">
                <el-icon><InfoFilled /></el-icon>
                <span>{{ nlHint }}</span>
              </div>
              <el-input
                v-model="execNLQuery"
                type="textarea"
                :rows="3"
                :placeholder="nlPlaceholder + ' (↑↓浏览历史)'"
                @keydown="handleNLKeyDown"
              />
              <el-button v-if="execRunning" type="danger" style="margin-top:10px" @click="stopExec">
                <el-icon><VideoPause /></el-icon> 停止
              </el-button>
              <el-button v-else type="primary" style="margin-top:10px" @click="handleRunSkillNL" :disabled="!execNLQuery.trim() || debugStreaming">
                <el-icon><VideoPlay /></el-icon> 执行
              </el-button>
            </el-tab-pane>

            <el-tab-pane label="命令行" name="cmd">
              <div class="cmd-input-row">
                <div v-if="cmdExamples.length" class="cmd-examples">
                  <div class="cmd-examples-title">示例命令</div>
                  <div v-for="(ex, i) in cmdExamples" :key="i" class="cmd-example-item" @click="execCmdStr = ex.cmd">
                    <code>{{ ex.cmd }}</code>
                    <span class="cmd-example-desc">{{ ex.desc }}</span>
                  </div>
                </div>

                <el-input v-model="execCmdStr" :placeholder="cmdPlaceholder" type="textarea" :rows="2" size="small" @keydown="handleCmdKeyDown" />
                <div v-if="cmdParseHint" class="cmd-parse-hint">
                  <el-tag size="small" type="info">{{ cmdParseHint }}</el-tag>
                </div>
              </div>
              <el-button v-if="execRunning" type="danger" style="margin-top:10px" @click="stopExec">
                <el-icon><VideoPause /></el-icon> 停止
              </el-button>
              <el-button v-else type="primary" style="margin-top:10px" @click="handleRunCmd" :disabled="!execCmdStr.trim() || debugStreaming">
                <el-icon><VideoPlay /></el-icon> 执行
              </el-button>
            </el-tab-pane>

          </el-tabs>
        </div>

        <div class="debug-right">
          <div class="debug-chat-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>AI 调试助手</span>
            <el-select
              v-model="debugScriptName"
              size="small"
              style="width: 160px; margin-left: 8px"
              :disabled="debugStreaming || execRunning"
            >
              <el-option
                v-for="s in debugSkill?.scripts || []"
                :key="s.name"
                :label="s.name"
                :value="s.name"
              />
            </el-select>
            <el-button
              size="small"
              type="warning"
              plain
              style="margin-left: auto"
              :loading="convertingPipeline"
              :disabled="debugStreaming || execRunning"
              @click="convertToPipeline"
            >
              <el-icon><Share /></el-icon> 转为流程
            </el-button>
            <el-button
              size="small"
              plain
              :loading="expLoading"
              @click="openExperience"
            >
              <el-icon><Document /></el-icon> 调试经验
            </el-button>
          </div>
          <div class="debug-message-list" ref="debugMsgListRef" @scroll="onSkillListScroll">
            <div v-if="debugMessages.length === 0 && !execRunning" class="debug-empty">
              <p>输入消息或使用左侧参数面板开始调试，例如"运行一下"、"帮我优化这个脚本"</p>
            </div>
            <div
              v-for="(msg, idx) in debugMessages"
              :key="idx"
              class="debug-message"
              :class="msg.role"
            >
              <div class="debug-msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">{{ agentName }}</el-avatar>
                <el-avatar :size="32" v-else style="background:#67c23a">我</el-avatar>
              </div>
              <div class="debug-msg-body">
                <div v-if="msg.role === 'user'" class="debug-msg-user">
                  {{ msg.content }}
                  <el-button text size="small" @click="copyText(msg.content)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                </div>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>推理过程<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
                      <el-button text size="small" @click.stop="copyText(msg.thinking)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                    </div>
                    <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
                  </div>
                  <el-collapse v-if="msg.content" :model-value="msg._contentOpen === false ? [] : ['content']" @change="(v: any) => { msg._contentOpen = v.length > 0 }">
                    <el-collapse-item name="content">
                      <template #title>
                        <span class="collapse-label">AI回复</span>
                        <el-button text size="small" @click.stop="copyText(msg.content)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                      </template>
                      <div class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.content)"></div>
                    </el-collapse-item>
                  </el-collapse>
                  <div v-if="msg.executingMsgs && msg.executingMsgs.length" class="debug-msg-executing">
                    <div v-for="(m, i) in msg.executingMsgs" :key="i" class="executing-line">
                      <el-icon v-if="i === msg.executingMsgs.length - 1" class="thinking-spin"><Loading /></el-icon>
                      <el-icon v-else class="executing-dot"><CircleCheck /></el-icon>
                      <span>{{ m }}</span>
                    </div>
                  </div>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                  <div v-if="msg.runResult" class="debug-msg-runresult">
                    <div class="runresult-header">
                      <el-tag :type="msg.runResult.success ? 'success' : 'danger'" size="small">
                        {{ msg.runResult.success ? '执行成功' : '执行失败' }}
                      </el-tag>
                      <span v-if="msg.runResult.execution_time_ms" class="exec-time">{{ msg.runResult.execution_time_ms }}ms</span>
                    </div>
                    <div v-if="msg.runResult.error" class="debug-result-error">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">错误信息</span>
                            <el-button text size="small" @click.stop="copyText(msg.runResult.error)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                          </template>
                          <pre>{{ msg.runResult.error }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.stdout" class="debug-result-stdout">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">标准输出</span>
                            <el-button text size="small" @click="copyText(msg.runResult.stdout)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                          </template>
                          <pre>{{ msg.runResult.stdout }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.result != null" class="debug-result-data">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">返回数据</span>
                            <el-button text size="small" @click.stop="copyText(formatResult(msg.runResult.result))" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> 复制</el-button>
                          </template>
                          <pre>{{ formatResult(msg.runResult.result) }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                  </div>
                  <div v-if="msg.inspectionResult" class="debug-msg-inspection">
                    <div class="inspection-header">
                      <el-tag :type="msg.inspectionResult.passed ? 'success' : 'warning'" size="small">
                        {{ msg.inspectionResult.passed ? '检查通过' : '发现问题' }}
                      </el-tag>
                      <span class="inspection-summary">{{ msg.inspectionResult.summary }}</span>
                      <el-button text size="small" @click="copyText(msg.inspectionResult.summary)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                    </div>
                    <div v-if="msg.inspectionResult.issues && msg.inspectionResult.issues.length" class="inspection-issues">
                      <div v-for="(issue, idx) in msg.inspectionResult.issues" :key="idx" class="inspection-issue-item">
                        <div class="inspection-issue-main">
                          <el-tag :type="issue.severity === 'fatal' ? 'danger' : issue.severity === 'error' ? 'error' : issue.severity === 'critical' ? 'error' : 'warning'" size="small">
                            {{ issue.severity }}
                          </el-tag>
                          <span class="inspection-issue-desc">{{ issue.description }}</span>
                          <el-button text size="small" @click="copyText(issue.description + (issue.suggestion ? '\n→ ' + issue.suggestion : ''))" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                        </div>
                        <div v-if="issue.suggestion" class="inspection-issue-suggestion">→ {{ issue.suggestion }}</div>
                      </div>
                    </div>
                    <div v-if="msg.inspectionResult.error" class="inspection-error">
                      <el-alert :title="msg.inspectionResult.error" type="warning" :closable="false" />
                    </div>
                  </div>
                  <div v-if="msg.scriptUpdated" class="debug-msg-script-updated">
                    <el-tag type="warning" size="small">脚本已更新: {{ msg.scriptUpdated }}</el-tag>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="(debugStreaming || execRunning) && !debugMessages.length" class="debug-message assistant">
              <div class="debug-msg-avatar"><el-avatar :size="32" style="background:#409eff">{{ agentName }}</el-avatar></div>
              <div class="debug-msg-body">
                <div class="typing-indicator"><span></span><span></span><span></span></div>
              </div>
            </div>
          </div>

          <div class="debug-input-area">
            <el-input
              v-model="debugInput"
              type="textarea"
              :rows="2"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="输入调试指令... (Enter发送, ↑↓浏览历史)"
              @keydown="handleDebugKeyDown"
              :disabled="debugStreaming || execRunning"
            />
            <el-button
              v-if="debugStreaming"
              type="danger"
              circle
              @click="stopDebugGeneration"
            >
              <el-icon><VideoPause /></el-icon>
            </el-button>
            <el-button
              v-else
              type="primary"
              circle
              :disabled="!debugInput.trim() || execRunning"
              @click="handleDebugSend"
            >
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <el-dialog v-model="showExperience" title="调试经验" width="680px">
      <div v-loading="expLoading">
        <el-tabs>
          <el-tab-pane label="归纳原因">
            <div v-if="experienceData.lessons" class="markdown-body" v-html="renderMarkdown(experienceData.lessons)"></div>
            <el-empty v-else description="暂无归纳经验，调试失败后会自动存储原因分析" :image-size="80" />
          </el-tab-pane>
          <el-tab-pane :label="`历史错误 (${(experienceData.negative || []).length})`">
            <div v-if="(experienceData.negative || []).length" style="max-height:400px;overflow-y:auto">
              <div v-for="(err, i) in experienceData.negative" :key="i" class="exp-error-item">
                <div class="exp-error-time">{{ err.timestamp }}</div>
                <div class="exp-error-msg"><pre>{{ err.error_message }}</pre></div>
                <div v-if="err.stdout_preview" class="exp-error-stdout"><pre>{{ err.stdout_preview }}</pre></div>
              </div>
            </div>
            <el-empty v-else description="暂无错误记录" :image-size="80" />
          </el-tab-pane>
          <el-tab-pane :label="`成功记录 (${(experienceData.positive || []).length})`">
            <div v-if="(experienceData.positive || []).length" style="max-height:400px;overflow-y:auto">
              <div v-for="(pos, i) in experienceData.positive" :key="i" class="exp-positive-item">
                <div class="exp-error-time">{{ pos.timestamp }}</div>
                <div class="exp-error-msg">{{ pos.result_summary }}</div>
              </div>
            </div>
            <el-empty v-else description="暂无成功记录" :image-size="80" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch, nextTick, type Ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Upload, Download, Delete, VideoPlay, CaretRight, Search, Check,
  MagicStick, Edit, CopyDocument, UploadFilled, CaretBottom, Loading,
  Promotion, ChatDotRound, InfoFilled, Share, VideoPause, CircleCheck,
} from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import markdownIt from 'markdown-it'

const router = useRouter()
const skills = ref<any[]>([])
const categories = ref<string[]>([])
const filterCategory = ref('')
const searchQuery = ref('')
const sortBy = ref('created')
const agentName = ref('DC')

async function loadAgentConfig() {
  try {
    const config = await api.get('/chat/agent/config')
    if (config && config.short_name) {
      agentName.value = config.short_name
    }
  } catch (e) {
    // 使用默认值
  }
}

const filteredSkills = computed(() => {
  let list = skills.value
  if (filterCategory.value) {
    list = list.filter((o: any) => o.category === filterCategory.value)
  }
  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase()
    list = list.filter(
      (o: any) =>
        (o.name || '').toLowerCase().includes(q) ||
        (o.display_name || '').toLowerCase().includes(q) ||
        (o.description || '').toLowerCase().includes(q)
    )
  }
  return list
})

const datasources = ref<any[]>([])


async function loadSkills() {
  try {
    skills.value = await api.get(`/skills?sort_by=${sortBy.value}`)
    categories.value = await api.get('/skills/categories')
  } catch (e: any) {
    ElMessage.error('加载技能失败')
  }
}

async function loadDatasources() {
  try {
    datasources.value = await api.get('/datasources')
  } catch (e: any) {
    /* ignore */
  }
}

function categoryColor(cat: string) {
  const map: Record<string, string> = {
    transform: 'primary',
    aggregate: 'success',
    join: 'warning',
    clean: 'info',
    analysis: 'danger',
    data_processing: '',
    ai_generated: 'success',
  }
  return map[cat] || ''
}

function truncateMarkdown(src: string): string {
  const text = src.replace(/---[\s\S]*?---/, '').replace(/^#+\s+.*$/gm, '').replace(/\*\*/g, '').replace(/`/g, '').trim()
  return text.length > 120 ? text.slice(0, 120) + '...' : text
}

const md = markdownIt({ html: false, breaks: true, linkify: true })

function renderMarkdown(src: string): string {
  return md.render(src)
}

function formatDate(d: string | null): string {
  if (!d) return '-'
  return new Date(d).toLocaleString()
}

function formatResult(result: any): string {
  try {
    return JSON.stringify(result, null, 2)
  } catch {
    return String(result)
  }
}

// ==================== 导入 ====================
const showUploadDialog = ref(false)

// 重名冲突处理
const showConflictDialog = ref(false)
const conflictInfo = ref<any>(null)
const pendingFile = ref<File | null>(null)
const renameValue = ref('')
const importing = ref(false)

function validateZip(file: any) {
  if (!file.name.toLowerCase().endsWith('.zip')) {
    ElMessage.error('只支持 .zip 格式的技能包')
    return false
  }
  return true
}

async function handleUploadZip(options: any) {
  pendingFile.value = options.file
  await doImport(options.file, 'check')
}

async function doImport(file: File, mode: string, newName?: string) {
  importing.value = true
  const formData = new FormData()
  formData.append('file', file)
  const params: any = { mode }
  if (newName) params.new_name = newName
  try {
    const res = await api.post('/skills/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
    })
    ElMessage.success(`技能 "${res.display_name || res.name}" 已导入`)
    showUploadDialog.value = false
    showConflictDialog.value = false
    pendingFile.value = null
    conflictInfo.value = null
    await loadSkills()
  } catch (e: any) {
    const status = e.response?.status
    const detail = e.response?.data?.detail
    if (status === 409 && detail && typeof detail === 'object') {
      // 重名冲突 → 弹出选择对话框
      conflictInfo.value = detail
      renameValue.value = `${detail.parsed_name}-copy`
      showConflictDialog.value = true
    } else {
      ElMessage.error(typeof detail === 'string' ? detail : '导入失败')
    }
  } finally {
    importing.value = false
  }
}

async function confirmOverwrite() {
  if (!pendingFile.value) return
  await doImport(pendingFile.value, 'overwrite')
}

async function confirmRename() {
  if (!pendingFile.value) return
  if (!renameValue.value.trim()) {
    ElMessage.warning('请输入新名称')
    return
  }
  await doImport(pendingFile.value, 'rename', renameValue.value.trim())
}

// ==================== 下载 ====================
function downloadSkill(skill: any) {
  const token = localStorage.getItem('access_token')
  const url = `/api/v1/skills/${skill.id}/download`
  if (token) {
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = blobUrl
        a.download = `${skill.name}.zip`
        a.click()
        URL.revokeObjectURL(blobUrl)
      })
  }
}

// ==================== 转为流程（调试页面内，流式推理） ====================

const convertingPipeline = ref(false)

// 调试经验
const showExperience = ref(false)
const expLoading = ref(false)
const experienceData = ref<any>({ lessons: '', negative: [], positive: [] })

async function openExperience() {
  if (!debugSkill.value) return
  showExperience.value = true
  expLoading.value = true
  try {
    experienceData.value = await api.get(`/skills/${debugSkill.value.id}/experience`)
  } catch (e: any) {
    ElMessage.error('加载经验失败')
  } finally {
    expLoading.value = false
  }
}

async function convertToPipeline() {
  if (!debugSkill.value || convertingPipeline.value) return

  convertingPipeline.value = true

  const assistantIdx = debugMessages.value.length
  debugMessages.value.push({
    role: 'assistant',
    content: '',
    thinking: '',
    thinkingOpen: false,
  })
  skillPinnedToBottom.value = true
  await nextTick()
  scrollSkillDebugToBottom(true)

  let streamOk = false
  let pipelineName = ''

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/pipelines/from-skill-stream/${debugSkill.value.id}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({}),
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const processLine = (line: string) => {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) return
      try {
        const data = JSON.parse(trimmed.slice(6))
        const msg = debugMessages.value[assistantIdx]
        if (data.type === 'status') {
          msg.content = (msg.content || '') + data.message + '\n'
        } else if (data.type === 'thinking') {
          msg.thinking = (msg.thinking || '') + data.content
        } else if (data.type === 'content') {
          msg.content += data.content
        } else if (data.type === 'done') {
          pipelineName = data.pipeline_name || data.name || '流程'
          streamOk = true
        } else if (data.type === 'error') {
          msg.content += `\n\n错误: ${data.message || data.content || '未知错误'}`
        }
      } catch { /* skip */ }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        const tail = decoder.decode()
        if (tail) buffer += tail
        if (buffer.trim()) {
          for (const line of buffer.split('\n')) processLine(line)
        }
        break
      }
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) processLine(line)
      nextTick(() => scrollSkillDebugToBottom())
    }

    if (streamOk) {
      const msg = debugMessages.value[assistantIdx]
      if (msg.thinking) msg.thinkingOpen = false
      msg.content = (msg.content || '') + `\n\n✅ 流程 "${pipelineName}" 已生成，可在流程页面查看。`
      ElMessage.success(`流程 "${pipelineName}" 已生成`)
      await loadSkills()
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      const msg = debugMessages.value[assistantIdx]
      if (msg) msg.content = `转为流程失败: ${e.message || String(e)}`
    }
  } finally {
    convertingPipeline.value = false
    await nextTick()
    scrollSkillDebugToBottom()
  }
}

async function confirmDelete(skill: any) {
  try {
    await ElMessageBox.confirm(
      `确定要删除技能 "${skill.display_name || skill.name}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await api.delete(`/skills/${skill.id}`)
    ElMessage.success('删除成功')
    await loadSkills()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  }
}

// ==================== 另存为 ====================
const showCloneDialog = ref(false)
const cloneTarget = ref<any>(null)
const cloneName = ref('')
const cloning = ref(false)

function openCloneDialog(skill: any) {
  cloneTarget.value = skill
  cloneName.value = (skill.display_name || skill.name) + ' (副本)'
  showCloneDialog.value = true
}

async function handleClone() {
  if (!cloneName.value.trim()) {
    ElMessage.warning('请输入新名称')
    return
  }
  if (!cloneTarget.value) return
  cloning.value = true
  try {
    const res = await api.post(`/skills/${cloneTarget.value.id}/clone`, {
      name: cloneName.value.trim(),
    })
    ElMessage.success(`技能 "${res.display_name || res.name}" 复制成功`)
    showCloneDialog.value = false
    cloneName.value = ''
    cloneTarget.value = null
    await loadSkills()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '复制失败')
  } finally {
    cloning.value = false
  }
}

// ==================== AI 生成 ====================
const showGenerateDialog = ref(false)
const generatePrompt = ref('')
const generating = ref(false)
let generateAbortController: AbortController | null = null
const genMessages = ref<any[]>([])
const genMsgListRef = ref<HTMLElement | null>(null)

// ==================== 相似技能检测 ====================
const showSimilarDialog = ref(false)
const similarSkills = ref<any[]>([])
const checkingSimilar = ref(false)

function onGenerateDialogClosed() {
  generatePrompt.value = ''
  genMessages.value = []
}

function stopGenerate() {
  if (generateAbortController) {
    generateAbortController.abort()
  }
}

function scrollGenMsg() {
  nextTick(() => {
    if (genMsgListRef.value) genMsgListRef.value.scrollTop = genMsgListRef.value.scrollHeight
  })
}

async function handleGenerate() {
  if (!generatePrompt.value.trim()) {
    ElMessage.warning('请输入需求描述')
    return
  }
  const userText = generatePrompt.value.trim()
  checkingSimilar.value = true
  try {
    const resp = await api.post('/skills/check-similar', { prompt: userText })
    if (resp.has_similar && resp.skills.length > 0) {
      similarSkills.value = resp.skills
      showSimilarDialog.value = true
      return
    }
  } catch {
    // 检测失败不阻断，继续生成
  } finally {
    checkingSimilar.value = false
  }
  await doGenerate(userText)
}

async function doGenerate(userText: string) {
  generating.value = true
  generateAbortController = new AbortController()
  pushHistory(genHistory, genHistoryIdx, userText, 'generate')
  genMessages.value.push({ role: 'user', content: userText, created_at: new Date().toISOString() })
  genMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false, created_at: new Date().toISOString() })

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch('/api/v1/skills/generate-stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ prompt: userText }),
      signal: generateAbortController.signal,
    })
    if (!response.ok) {
      const err = await response.text()
      throw new Error(err)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let thinkingDone = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          const msg = genMessages.value[genMessages.value.length - 1]
          if (data.type === 'model') {
            msg.model = data.content
          } else if (data.type === 'clear_thinking') {
            msg.thinking = ''; msg.content = ''; msg.thinkingOpen = false; thinkingDone = false
          } else if (data.type === 'thinking') {
            if (thinkingDone && msg.thinking) { msg.thinking += '\n\n--- 新一轮推理 ---\n'; msg.thinkingOpen = false; thinkingDone = false }
            if (!msg.thinking) msg.thinkingOpen = false
            msg.thinking = (msg.thinking || '') + data.content
          } else if (data.type === 'chunk') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            msg.content += data.content
          } else if (data.type === 'status' || data.type === 'progress') {
            if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
            msg.content += (msg.content ? '\n' : '') + `**[${data.message}]**`
          } else if (data.type === 'warning') {
            msg.content += (msg.content ? '\n' : '') + `⚠ ${data.message}`
          } else if (data.type === 'done') {
            if (msg.thinking && !thinkingDone) { msg.thinkingOpen = false }
            msg.content += (msg.content ? '\n\n' : '') + data.message
          } else if (data.type === 'error') {
            msg.content += (msg.content ? '\n\n' : '') + `❌ ${data.message}`
            ElMessage.error(data.message)
          } else if (data.type === 'created') {
            const skill = data.skill
            msg.content += (msg.content ? '\n\n' : '') + `✅ 技能 "${skill.display_name || skill.name}" 已创建`
            ElMessage.success(`技能 "${skill.display_name || skill.name}" 已生成`)
            showGenerateDialog.value = false
            await loadSkills()
            detailSkill.value = skill
            mdEditContent.value = skill.skill_md || ''
            modifyInstruction.value = ''
            detailTab.value = 'md'
            detailDrawer.value = true
          }
          scrollGenMsg()
        } catch {}
      }
    }
  } catch (e: any) {
    const msg = genMessages.value[genMessages.value.length - 1]
    if (msg) {
      if (e.name === 'AbortError') {
        msg.content += '\n\n*[已停止生成]*'
      } else {
        msg.content += `\n\n❌ ${e.message || '生成失败'}`
      }
    }
  } finally {
    generating.value = false
    generateAbortController = null
  }
}

async function openExistingSkill(skill: any) {
  showSimilarDialog.value = false
  showGenerateDialog.value = false
  await loadSkills()
  const found = skills.value.find((s: any) => s.id === skill.id)
  if (found) {
    detailSkill.value = found
    mdEditContent.value = found.skill_md || ''
    modifyInstruction.value = ''
    detailTab.value = 'md'
    detailDrawer.value = true
  }
}

async function proceedToGenerate() {
  showSimilarDialog.value = false
  await doGenerate(generatePrompt.value.trim())
}

// ==================== 技能详情/修改 ====================
const detailDrawer = ref(false)
const detailSkill = ref<any>(null)
const detailTab = ref('md')
const mdEditContent = ref('')
const mdMode = ref<'preview' | 'edit'>('preview')
const savingMd = ref(false)
const modifyInstruction = ref('')
const modifying = ref(false)
const modifyError = ref('')
const modifyMessages = ref<any[]>([])
const modifyAbortCtrl = ref<AbortController | null>(null)

const expandedScript = ref('')
const scriptContents = reactive<Record<string, string>>({})
const savingScript = ref(false)

function openDetail(skill: any) {
  detailSkill.value = skill
  mdEditContent.value = skill.skill_md || ''
  modifyInstruction.value = ''
  modifyError.value = ''
  modifyMessages.value = []
  detailTab.value = 'md'

  Object.keys(scriptContents).forEach(k => delete scriptContents[k])
  expandedScript.value = ''
  for (const s of (skill.scripts || [])) {
    scriptContents[s.name] = ''
  }

  detailDrawer.value = true
}

async function handleModifySkill() {
  if (!detailSkill.value || !modifyInstruction.value.trim()) return
  modifying.value = true
  modifyError.value = ''
  const userText = modifyInstruction.value.trim()
  pushHistory(modifyHistory, modifyHistoryIdx, userText, 'modify')
  modifyMessages.value.push({ role: 'user', content: userText, created_at: new Date().toISOString() })
  modifyMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false, created_at: new Date().toISOString() })

  const ctrl = new AbortController()
  modifyAbortCtrl.value = ctrl

  try {
    const token = localStorage.getItem('access_token')
    const response = await fetch(`/api/v1/skills/${detailSkill.value.id}/modify-stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ instruction: userText }),
      signal: ctrl.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let doneSkill: any = null
    let cancelled = false
    let errMsg = ''
    let thinkingDone = false

    const processLine = (line: string) => {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) return
      try {
        const data = JSON.parse(trimmed.slice(6))
        const msg = modifyMessages.value[modifyMessages.value.length - 1]
        if (data.type === 'clear_thinking') {
          msg.thinking = ''; msg.content = ''; msg.thinkingOpen = false; thinkingDone = false
        } else if (data.type === 'thinking') {
          if (thinkingDone && msg.thinking) { msg.thinking += '\n\n--- 新一轮推理 ---\n'; msg.thinkingOpen = false; thinkingDone = false }
          if (!msg.thinking) msg.thinkingOpen = false
          msg.thinking = (msg.thinking || '') + data.content
        } else if (data.type === 'content') {
          if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
          msg.content += data.content
        } else if (data.type === 'done') {
          doneSkill = data.skill || null
          if (msg.thinking && !thinkingDone) msg.thinkingOpen = false
        } else if (data.type === 'error') {
          errMsg = data.content || '修改失败'
        } else if (data.type === 'cancelled') {
          cancelled = true
        }
      } catch {
        // skip malformed JSON
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        const tail = decoder.decode()
        if (tail) buffer += tail
        if (buffer.trim()) {
          for (const line of buffer.split('\n')) {
            processLine(line)
          }
        }
        break
      }

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        processLine(line)
      }
    }

    if (errMsg) {
      modifyError.value = errMsg
    } else if (cancelled) {
      ElMessage.info('修改已取消')
    } else if (doneSkill) {
      detailSkill.value = doneSkill
      mdEditContent.value = doneSkill.skill_md || ''
      modifyInstruction.value = ''
      ElMessage.success('技能已通过 AI 修改')
      await loadSkills()
      if (debugDrawer.value) {
        refreshDebugContext()
      }
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      modifyError.value = e.response?.data?.detail || e.message || '修改失败，请检查 LLM 配置'
    }
  } finally {
    modifying.value = false
    modifyAbortCtrl.value = null
  }
}

async function toggleScript(name: string) {
  if (expandedScript.value === name) {
    expandedScript.value = ''
    return
  }
  expandedScript.value = name
  if (!scriptContents[name]) {
    try {
      const res = await api.get(`/skills/${detailSkill.value.id}/scripts/${name}`)
      scriptContents[name] = res.content || ''
    } catch (e: any) {
      ElMessage.error('加载脚本失败')
    }
  }
}

async function saveScriptContent(name: string) {
  if (!detailSkill.value) return
  savingScript.value = true
  try {
    await api.put(`/skills/${detailSkill.value.id}/scripts/${name}`, {
      content: scriptContents[name],
    })
    ElMessage.success(`脚本 ${name} 已保存`)
    detailSkill.value.scripts = await api.get(`/skills/${detailSkill.value.id}/scripts`)
    if (debugDrawer.value) {
      refreshDebugContext()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingScript.value = false
  }
}

async function saveSkillMd() {
  if (!detailSkill.value) return
  savingMd.value = true
  try {
    const updated = await api.put(`/skills/${detailSkill.value.id}/skill-md`, {
      content: mdEditContent.value,
    })
    detailSkill.value = updated
    mdEditContent.value = updated.skill_md || mdEditContent.value
    const idx = skills.value.findIndex((s: any) => s.id === updated.id)
    if (idx >= 0) skills.value[idx] = updated
    ElMessage.success('SKILL.md 已保存')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingMd.value = false
  }
}

// ==================== 调试技能 ====================
const debugDrawer = ref(false)
const debugSkill = ref<any>(null)
const debugScriptName = ref('main.py')

// 息屏防护：页面不可见时阻止对话框关闭
watch(debugDrawer, (newVal, oldVal) => {
  if (oldVal === true && newVal === false && document.hidden) {
    nextTick(() => { debugDrawer.value = true })
  }
})

function handleDebugBeforeClose(done: () => void) {
  if (debugStreaming.value || execRunning.value) {
    ElMessage.warning('正在执行中，请先等待完成或点击停止')
    return
  }
  done()
}

// 执行面板
const execRunning = ref(false)
let execAbortController: AbortController | null = null
const execResult = ref<any>(null)
const execThinking = ref('')
const execPhase = ref<'thinking' | 'executing' | 'idle'>('idle')
const execTab = ref('nl')

function stopExec() {
  if (execAbortController) {
    execAbortController.abort()
    execAbortController = null
  }
  execRunning.value = false
  execPhase.value = 'idle'
}

function pushExecResult(result: any, thinking = '') {
  debugMessages.value.push({
    role: 'assistant',
    content: result?.success ? '执行完成' : '执行失败',
    thinking: thinking || undefined,
    runResult: result,
  })
  execResult.value = null
  execThinking.value = ''
  nextTick(() => {
    if (debugMsgListRef.value) {
      debugMsgListRef.value.scrollTop = debugMsgListRef.value.scrollHeight
    }
  })
}
const execNLQuery = ref('')
const execCmdStr = ref('')
const skillParams = ref<any[]>([])
const cmdParamValues = reactive<Record<string, any>>({})
const cmdExampleDsName = ref('')
const cmdExampleTableName = ref('')

// Chat 面板
interface DebugMessage {
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  thinkingOpen?: boolean
  runResult?: any
  scriptUpdated?: string
  model?: string
  executingMsg?: string
  executingMsgs?: string[]
  created_at?: string
}

const debugMessages = ref<DebugMessage[]>([])
const debugInput = ref('')
const debugStreaming = ref(false)
const debugMsgListRef = ref<HTMLElement>()
let debugAbortController: AbortController | null = null
const skillPinnedToBottom = ref(true)

function formatMsgTime(ts?: string): string {
  if (!ts) return ''
  try { return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) } catch { return '' }
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

function scrollSkillDebugToBottom(force = false) {
  const el = debugMsgListRef.value
  if (!el) return
  if (!force && !skillPinnedToBottom.value) return
  el.scrollTop = el.scrollHeight
}
function scrollThinkingBodyToBottom(msgIdx: number) {
  nextTick(() => {
    const list = debugMsgListRef.value
    if (!list) return
    const msgs = list.querySelectorAll('.debug-message')
    const target = msgs[msgIdx] as HTMLElement | undefined
    if (target) {
      const body = target.querySelector('.thinking-body') as HTMLElement | null
      if (body) body.scrollTop = body.scrollHeight
    }
    scrollSkillDebugToBottom()
  })
}
function onSkillListScroll() {
  const el = debugMsgListRef.value
  if (!el) return
  skillPinnedToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

// 执行流式：在消息列表中开一条 live 助手消息，返回其索引
function startExecMessage(userText: string, initialExecutingMsg?: string): number {
  debugMessages.value.push({ role: 'user', content: userText, created_at: new Date().toISOString() })
  const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  debugMessages.value.push({ role: 'assistant', content: '', llmContent: '', thinking: '', thinkingOpen: false, executingMsgs: initialExecutingMsg ? [`[${timeStr}] ${initialExecutingMsg}`] : [], created_at: new Date().toISOString() })
  nextTick(() => scrollSkillDebugToBottom(true))
  return debugMessages.value.length - 1
}
function setExecutingMsg(msg: any, text: string) {
  if (!text) return
  if (!msg.executingMsgs) msg.executingMsgs = []
  const timeStr = new Date().toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const tagged = `[${timeStr}] ${text}`
  const last = msg.executingMsgs[msg.executingMsgs.length - 1]
  const lastText = last ? last.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '') : ''
  if (last && lastText === text) {
    msg.executingMsgs[msg.executingMsgs.length - 1] = tagged
  } else {
    msg.executingMsgs.push(tagged)
  }
}
function clearExecutingMsg(msg: any) {
  msg.executingMsgs = []
}
function archiveExecutingMsg(msg: any) {
  // 阶段切换时：把执行日志存到独立字段，不拼进 content（保持 content 纯净给 LLM）
  if (msg.executingMsgs && msg.executingMsgs.length > 0) {
    msg.stdouts = msg.stdouts || []
    msg.stdouts.push(msg.executingMsgs.join('\n'))
    msg.executingMsgs = []
  }
}
function finalizeExecMessage(idx: number, result: any) {
  const msg = debugMessages.value[idx]
  if (msg) {
    msg.runResult = result
    if (!msg.content) msg.content = result?.success ? '执行完成' : '执行失败'
  }
  nextTick(() => scrollSkillDebugToBottom())
}

/** 公共 debug SSE 事件处理（三处 handler 共享）。
 *  返回值：'break' 表示应中断 SSE 循环（done/error/give_up/fatal），null 表示继续。
 */
function processDebugSSEEvent(
  data: any,
  msg: any,
  state: { thinkingDone: boolean; scriptChanged: boolean; result: any },
  assistantIdx: number,
): 'break' | null {
  const setThinkingDone = () => {
    if (!state.thinkingDone && msg.thinking) {
      state.thinkingDone = true
      msg.thinkingOpen = false
    }
  }

  switch (data.type) {
    case 'model':
      msg.model = data.content
      break
    case 'ping':
      break
    case 'clear_thinking':
      msg.thinking = ''; msg.content = ''; msg.llmContent = ''; msg.thinkingOpen = false; state.thinkingDone = false
      break
    case 'thinking':
      if (state.thinkingDone && msg.thinking) {
        msg.thinking += '\n\n--- 新一轮推理 ---\n'
        msg.thinkingOpen = false
        state.thinkingDone = false
      }
      if (!msg.thinking) msg.thinkingOpen = false
      msg.thinking = (msg.thinking || '') + data.content
      scrollThinkingBodyToBottom(assistantIdx)
      break
    case 'content':
      setThinkingDone()
      execPhase.value = 'executing'
      if (!msg.content) msg.content = ''
      msg.content += data.content
      msg.llmContent = (msg.llmContent || '') + data.content
      break
    case 'tool_action': {
      // 工具调用显示卡片（不进 llmContent）
      msg.toolActions = msg.toolActions || []
      const _taTime = new Date().toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      for (const act of (data.actions || [])) {
        const icon = act.icon || ''
        const script = act.script || 'main.py'
        const detail = act.detail || ''
        let line = `[${_taTime}] ${icon} ${script}${detail ? ' ' + detail : ''}`
        if (act.diff) {
          line += '\n```diff\n' + act.diff + '\n```'
        }
        msg.content += (msg.content ? '\n' : '') + line
        msg.toolActions.push(act)
      }
      break
    }
    case 'tool_summary': {
      // 工具结果摘要（不进 llmContent）
      const _tsTime = new Date().toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
      for (const s of (data.summaries || [])) {
        msg.content += (msg.content ? '\n' : '') + `[${_tsTime}] ${s}`
      }
      break
    }
    case 'executing':
      execPhase.value = 'executing'
      setExecutingMsg(msg, data.message || '正在执行技能脚本...')
      setThinkingDone()
      break
    case 'progress':
      setExecutingMsg(msg, data.message || '')
      break
    case 'inspecting':
      archiveExecutingMsg(msg)
      msg.content += `\n\n🔍 ${data.message || 'DataInspector 正在检查数据质量...'}\n`
      msg.thinkingOpen = false
      state.thinkingDone = true
      break
    case 'inspection_result':
      msg.inspectionResult = data.result
      break
    case 'inspection_report':
      msg.inspectionReport = data.report
      msg.content += (msg.content ? '\n\n' : '') + data.report + '\n'
      break
    case 'retry':
      archiveExecutingMsg(msg)
      msg.content += `\n\n---\n🔄 ${data.message || '开始修复...'}\n`
      msg.thinkingOpen = false
      state.thinkingDone = true
      break
    case 'round':
      archiveExecutingMsg(msg)
      msg.thinkingOpen = false
      state.thinkingDone = true
      msg.content += `\n\n─── 第${data.round}次${data.action === 'execute' ? '执行' : '修改'} ───\n`
      break
    case 'fixing':
      execPhase.value = 'executing'
      archiveExecutingMsg(msg)
      msg.content += `\n\n🔧 ${data.message || '正在自动修复...'}\n`
      break
    case 'run_result':
      setThinkingDone()
      archiveExecutingMsg(msg)
      msg.runResult = data.result
      {
        const r = data.result || {}
        const inner = typeof r.result === 'object' && r.result ? r.result : {}
        const failed = !r.success || inner.success === false || (r.error && String(r.error).trim()) || (inner.error && String(inner.error).trim())
        if (failed) {
          const errMsg = String(r.error || inner.error || '未知错误').substring(0, 300)
          msg.content += `\n❌ 执行失败：${errMsg}\n`
        } else if (!msg.content) {
          msg.content = '技能执行完成'
        }
      }
      break
    case 'script_updated':
      msg.scriptUpdated = data.script_name
      state.scriptChanged = true
      refreshDebugContext()
      break
    case 'give_up':
      archiveExecutingMsg(msg)
      msg.content += `\n\n⚠ **修复失败**${data.reason ? '\n' + data.reason : '——无法自动修复'}`
      state.result = { success: false, error: data.reason || '修复失败' }
      return 'break'
    case 'platform_issue':
      archiveExecutingMsg(msg)
      msg.content += `\n\n🔧 **平台能力缺失——这不是脚本问题，修改脚本无法解决**\n\n${data.message || ''}\n`
      msg.thinkingOpen = false
      state.thinkingDone = true
      break
    case 'fatal': {
      const issues = data.issues || []
      let fatalText = `\n\n🚫 **致命问题——数据违反法律法规，已停止处理**\n\n${data.summary || ''}\n`
      for (const issue of issues) {
        fatalText += `\n- [FATAL] ${issue.description || ''}`
        if (issue.suggestion) fatalText += `\n  → ${issue.suggestion}`
      }
      msg.content += fatalText
      state.result = { success: false, error: '致命问题' }
      return 'break'
    }
    case 'warning_confirmation': {
      const issues = data.issues || []
      let warnText = `\n\n⚠ **检查发现以下警告问题，是否需要修复？**\n\n${data.summary || ''}\n`
      for (const issue of issues) {
        warnText += `\n- [WARNING] ${issue.description || ''}`
        if (issue.column) warnText += ` (列: ${issue.column})`
        if (issue.suggestion) warnText += `\n  → ${issue.suggestion}`
      }
      warnText += '\n\n> 如需修复，请回复"修复警告问题"'
      msg.content += warnText
      break
    }
    case 'done':
      if (data.result != null) {
        state.result = data.result
      }
      if (!msg.content || msg.content.trim() === '') {
        msg.content = '✅ 调试完成'
      } else if (!msg.content.includes('✅') && !msg.content.includes('⚠') && !msg.content.includes('🔧') && !msg.content.includes('🚫')) {
        msg.content += '\n\n✅ 调试完成'
      }
      msg.thinkingOpen = false
      archiveExecutingMsg(msg)
      return 'break'
    case 'error':
      msg.content += `\n\n错误: ${data.content || '未知错误'}`
      state.result = { success: false, error: data.content || '执行失败' }
      return 'break'
  }
  return null
}

/** 公共 SSE 流读取（三处 handler 共享） */
async function readDebugSSEStream(
  response: Response,
  assistantIdx: number,
  scriptChangedRef: { value: boolean },
): Promise<{ result: any; streamOk: boolean }> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const state = { thinkingDone: false, scriptChanged: false, result: null as any }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue
      try {
        const data = JSON.parse(trimmed.slice(6))
        const msg = debugMessages.value[assistantIdx]
        const ret = processDebugSSEEvent(data, msg, state, assistantIdx)
        if (ret === 'break') {
          // drain 剩余流
          try { await reader.read() } catch {}
          scriptChangedRef.value = state.scriptChanged
          return { result: state.result, streamOk: true }
        }
      } catch {
        // skip malformed JSON
      }
    }
    nextTick(() => scrollSkillDebugToBottom())
  }

  scriptChangedRef.value = state.scriptChanged
  return { result: state.result, streamOk: true }
}

// ==================== 输入历史记录（localStorage 持久化） ====================
const HISTORY_MAX = 100

function loadHistory(key: string): string[] {
  try {
    const raw = localStorage.getItem(`dc_skill_history_${key}`)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveHistory(key: string, list: string[]) {
  try {
    localStorage.setItem(`dc_skill_history_${key}`, JSON.stringify(list.slice(-HISTORY_MAX)))
  } catch {}
}

const nlHistory = ref<string[]>(loadHistory('nl'))
const nlHistoryIdx = ref(-1)
const cmdHistory = ref<string[]>(loadHistory('cmd'))
const cmdHistoryIdx = ref(-1)
const chatHistory = ref<string[]>(loadHistory('chat'))
const chatHistoryIdx = ref(-1)
const genHistory = ref<string[]>(loadHistory('generate'))
const genHistoryIdx = ref(-1)
const genDraft = ref('')
const modifyHistory = ref<string[]>(loadHistory('modify'))
const modifyHistoryIdx = ref(-1)
const modifyDraft = ref('')

function pushHistory(list: Ref<string[]>, idx: Ref<number>, value: string, storageKey: string) {
  const v = value.trim()
  if (!v) return
  if (list.value[list.value.length - 1] !== v) {
    list.value.push(v)
    if (list.value.length > HISTORY_MAX) {
      list.value = list.value.slice(-HISTORY_MAX)
    }
    saveHistory(storageKey, list.value)
  }
  idx.value = -1
}

function onHistoryKey(e: KeyboardEvent, list: Ref<string[]>, idx: Ref<number>, model: Ref<string>, savedDraft: Ref<string>) {
  if (e.key === 'ArrowUp') {
    if (list.value.length === 0) return
    e.preventDefault()
    if (idx.value === -1) {
      savedDraft.value = model.value
      idx.value = list.value.length - 1
    } else if (idx.value > 0) {
      idx.value--
    }
    model.value = list.value[idx.value]
  } else if (e.key === 'ArrowDown') {
    if (idx.value === -1) return
    e.preventDefault()
    if (idx.value < list.value.length - 1) {
      idx.value++
      model.value = list.value[idx.value]
    } else {
      idx.value = -1
      model.value = savedDraft.value
    }
  }
}

const nlDraft = ref('')
const cmdDraft = ref('')
const chatDraft = ref('')

function onGenHistoryKey(e: KeyboardEvent) {
  onHistoryKey(e, genHistory, genHistoryIdx, generatePrompt, genDraft)
}
function onModifyHistoryKey(e: KeyboardEvent) {
  onHistoryKey(e, modifyHistory, modifyHistoryIdx, modifyInstruction, modifyDraft)
}

const cmdPlaceholder = computed(() => {
  const name = debugSkill.value?.name || 'skill'
  if (skillParams.value.length) {
    const paramHint = skillParams.value
      .filter((p: any) => p.required)
      .map((p: any) => `${p.name}=<${p.type}>`)
      .join(' ')
    return `/${name} ${paramHint}`
  }
  return `/${name} 参数1=值1 参数2=值2`
})

const nlExamples = computed(() => {
  if (!debugSkill.value) return []
  const md = debugSkill.value.skill_md || ''
  if (!md) return []
  const examples: string[] = []
  const lines = md.split('\n')
  let inUsage = false
  let usageLevel = 0
  let collectingCodeBlock = false
  let codeBuf = ''
  for (const line of lines) {
    const heading = line.trim().match(/^(#{1,4})\s+(.*)/)
    if (heading) {
      const level = heading[1].length
      const title = heading[2].replace(/[📌🚀📋💡📝🔍]/g, '').trim()
      if (!inUsage && /使用方式|用法|使用示例|示例|调用|如何使用/i.test(title)) {
        inUsage = true
        usageLevel = level
        continue
      }
      if (inUsage && level <= usageLevel) {
        inUsage = false
        if (collectingCodeBlock) {
          collectingCodeBlock = false
          if (codeBuf.trim()) examples.push(codeBuf.trim())
          codeBuf = ''
        }
        continue
      }
    }
    if (inUsage) {
      if (line.trim().startsWith('```')) {
        if (collectingCodeBlock) {
          collectingCodeBlock = false
          if (codeBuf.trim()) examples.push(codeBuf.trim())
          codeBuf = ''
        } else {
          collectingCodeBlock = true
          codeBuf = ''
        }
        continue
      }
      if (collectingCodeBlock) {
        codeBuf += line + '\n'
      } else {
        const trimmed = line.trim()
        if (trimmed && !trimmed.startsWith('|') && !trimmed.startsWith('#') && !trimmed.startsWith('-') && trimmed.length > 5 && trimmed.length < 200) {
          if (/例如|比如|示例|将["""]|从["""]|对["""]|查找|筛选|统计|导出|清洗|迁移|转换/.test(trimmed)) {
            examples.push(trimmed)
          }
        }
      }
    }
  }
  return examples.slice(0, 3)
})

const nlHint = computed(() => {
  if (!debugSkill.value) return ''
  const skill = debugSkill.value
  const desc = skill.description || ''
  const examples = nlExamples.value
  if (examples.length > 0) return ''
  if (desc.includes('清洗') || desc.includes('去重')) {
    return '告诉我要清洗哪个数据源的哪个表，我会帮你去除重复和空值数据'
  }
  if (desc.includes('检索') || desc.includes('搜索') || desc.includes('查询')) {
    return '用自然语言描述你想查找的内容，我会帮你检索相关数据'
  }
  if (desc.includes('分析') || desc.includes('统计')) {
    return '描述你想分析的数据维度，我会生成统计报告'
  }
  if (desc.includes('导出')) {
    return '告诉我要导出哪些数据，我会帮你生成文件'
  }
  if (desc.includes('采集') || desc.includes('爬取')) {
    return '描述要采集的数据来源和数量，我会帮你获取数据'
  }
  if (desc.includes('转换') || desc.includes('处理')) {
    return '描述数据转换需求，我会帮你处理数据'
  }
  return ''
})

const nlPlaceholder = computed(() => {
  if (!debugSkill.value) return '用自然语言描述你想做什么'
  const examples = nlExamples.value
  if (examples.length > 0) {
    return examples[0]
  }
  const skill = debugSkill.value
  const name = skill.display_name || skill.name || ''
  const desc = skill.description || ''
  const params = skillParams.value
  if (name.includes('文物') || desc.includes('文物')) {
    return '例如：检索明代的青铜器，限制返回20条'
  }
  if (desc.includes('清洗') || desc.includes('去重')) {
    return '例如：清洗"文物"数据源的"全国文物"表，去除重复数据'
  }
  if (desc.includes('检索') || desc.includes('搜索')) {
    if (params.length > 0) {
      const pExamples = params.slice(0, 2).map((p: any) => {
        if (p.example) return `${p.name}为${p.example}`
        return `${p.name}为某个值`
      })
      return `例如：查找${pExamples.join('，')}的数据`
    }
    return '例如：查找符合条件的数据'
  }
  if (desc.includes('分析') || desc.includes('统计')) {
    return '例如：统计各类型数据的分布情况'
  }
  if (desc.includes('导出')) {
    return '例如：导出查询结果到Excel文件'
  }
  if (desc.includes('采集')) {
    return '例如：采集100条数据并保存'
  }
  if (params.length > 0) {
    const requiredParams = params.filter((p: any) => p.required)
    if (requiredParams.length > 0) {
      const firstParam = requiredParams[0]
      if (firstParam.example) {
        return `例如：设置${firstParam.name}为${firstParam.example}`
      }
    }
  }
  return '用自然语言描述你想做什么'
})

const cmdParseHint = computed(() => {
  const cmd = execCmdStr.value.trim()
  if (!cmd || !cmd.startsWith('/')) return ''
  const parts = cmd.split(/\s+/)
  const skillName = parts[0].slice(1)
  const params: Record<string, string> = {}
  for (let i = 1; i < parts.length; i++) {
    const eq = parts[i].indexOf('=')
    if (eq > 0) {
      params[parts[i].slice(0, eq)] = parts[i].slice(eq + 1)
    }
  }
  const paramKeys = Object.keys(params)
  if (paramKeys.length === 0) return `技能: ${skillName}（无参数）`
  return `技能: ${skillName} | ${paramKeys.map(k => `${k}=${params[k]}`).join(', ')}`
})

const cmdExamples = computed(() => {
  const name = debugSkill.value?.name || 'skill'
  const params = skillParams.value
  const examples: { cmd: string; desc: string }[] = []
  
  const firstDs = datasources.value?.[0]
  const dsName = cmdExampleDsName.value || firstDs?.name || ''
  const tblName = cmdExampleTableName.value || ''

  function paramValue(p: any): string {
    if (p.is_datasource) return dsName || '数据源名'
    if (p.is_table) return tblName || '表名'
    if (p.example) return String(p.example)
    if (p.default !== undefined && p.default !== null) return String(p.default)
    if (p.type === 'bool') return 'true'
    if (p.type === 'int' || p.type === 'float') {
      if (p.name.includes('limit') || p.name.includes('count')) return '10'
      if (p.name.includes('max')) return '100'
      return '1'
    }
    if (p.name.includes('path') || p.name.includes('file') || p.name.includes('log')) return './output.log'
    if (p.name.includes('name')) return '名称'
    if (p.name.includes('id')) return 'ID'
    return '值'
  }

  if (!params.length) {
    examples.push({ cmd: `/${name}`, desc: '基本调用' })
    examples.push({ cmd: `/${name} param1=value1 param2=value2`, desc: '带参数调用' })
    return examples
  }

  const required = params.filter((p: any) => p.required)
  const optional = params.filter((p: any) => !p.required)

  if (required.length > 0) {
    const requiredPart = required.map((p: any) => `${p.name}=${paramValue(p)}`).join(' ')
    examples.push({ cmd: `/${name} ${requiredPart}`, desc: '必填参数' })
  } else {
    examples.push({ cmd: `/${name}`, desc: '基本调用' })
  }

  const additionalParams = optional.slice(0, 2)
  if (additionalParams.length > 0) {
    const allParams = [...required, ...additionalParams]
    const allPart = allParams.map((p: any) => `${p.name}=${paramValue(p)}`).join(' ')
    examples.push({ cmd: `/${name} ${allPart}`, desc: '完整参数' })
  }

  return examples
})




function resetDebug() {
  debugSkill.value = null
  execRunning.value = false
  execResult.value = null
  execThinking.value = ''
  execPhase.value = 'idle'
  execNLQuery.value = ''
  execCmdStr.value = ''
  execTab.value = 'nl'
  skillParams.value = []
  cmdExampleDsName.value = ''
  cmdExampleTableName.value = ''
  debugMessages.value = []
  debugInput.value = ''
  debugStreaming.value = false
  if (execAbortController) {
    execAbortController.abort()
    execAbortController = null
  }
}

async function openDebug(skill: any, scriptName?: string) {
  let freshSkill = skill
  try {
    const detail = await api.get(`/skills/${skill.id}`)
    if (detail) freshSkill = detail
  } catch { /* use passed skill */ }

  debugSkill.value = freshSkill
  debugScriptName.value = scriptName || (freshSkill.scripts?.[0]?.name || 'main.py')
  execResult.value = null
  execThinking.value = ''
  execPhase.value = 'idle'
  execNLQuery.value = ''
  execCmdStr.value = `/${freshSkill.name || 'skill'} `
  execTab.value = 'nl'
  skillParams.value = []
  debugMessages.value = []
  debugInput.value = ''
  debugStreaming.value = false
  debugDrawer.value = true

  try {
    const params = await api.get(`/skills/${freshSkill.id}/params`)
    skillParams.value = params || []
    for (const p of params) {
      if (p.default !== null && p.default !== undefined) {
        cmdParamValues[p.name] = p.default
      } else if (p.type === 'bool') {
        cmdParamValues[p.name] = false
      } else {
        cmdParamValues[p.name] = ''
      }
    }

    const hasDs = params.some((p: any) => p.is_datasource)
    if (hasDs && datasources.value.length) {
      const ds = datasources.value[0]
      cmdExampleDsName.value = ds.name || ''
      try {
        const tree = await api.get(`/datasources/${ds.id}/tree`)
        const tableNodes = (tree || []).filter((n: any) => n.type === 'excel_sheet' || n.type === 'csv' || n.type === 'table')
        if (tableNodes.length) {
          cmdExampleTableName.value = tableNodes[0].label || tableNodes[0].metadata?.table_name || ''
        }
      } catch { /* ignore */ }
    }
  } catch {
    /* ignore */
  }
}

async function refreshDebugContext() {
  if (!debugSkill.value) return
  try {
    const detail = await api.get(`/skills/${debugSkill.value.id}`)
    if (detail) {
      debugSkill.value = { ...debugSkill.value, ...detail }
    }
    const params = await api.get(`/skills/${debugSkill.value.id}/params`)
    skillParams.value = params || []
    for (const p of params) {
      if (!(p.name in cmdParamValues)) {
        if (p.default !== null && p.default !== undefined) {
          cmdParamValues[p.name] = p.default
        } else if (p.type === 'bool') {
          cmdParamValues[p.name] = false
        } else {
          cmdParamValues[p.name] = ''
        }
      }
    }

    const hasDs = params.some((p: any) => p.is_datasource)
    if (hasDs && datasources.value.length) {
      const ds = datasources.value[0]
      cmdExampleDsName.value = ds.name || ''
      try {
        const tree = await api.get(`/datasources/${ds.id}/tree`)
        const tableNodes = (tree || []).filter((n: any) => n.type === 'excel_sheet' || n.type === 'csv' || n.type === 'table')
        if (tableNodes.length) {
          cmdExampleTableName.value = tableNodes[0].label || tableNodes[0].metadata?.table_name || ''
        }
      } catch { /* ignore */ }
    }

    buildCmdFromParams()
  } catch { /* ignore */ }
}

function buildCmdFromParams() {
  const name = debugSkill.value?.name || 'skill'
  const parts = [`/${name}`]
  for (const p of skillParams.value) {
    const val = cmdParamValues[p.name]
    if (val === '' || val === null || val === undefined) continue
    if (p.is_datasource) {
      parts.push(`datasource=${val}`)
    } else if (p.is_table) {
      parts.push(`tables=${Array.isArray(val) ? val.join(',') : val}`)
    } else if (p.is_list && Array.isArray(val)) {
      parts.push(`${p.name}=${val.join(',')}`)
    } else {
      parts.push(`${p.name}=${val}`)
    }
  }
  execCmdStr.value = parts.join(' ')
}

async function handleRunSkillNL() {
  if (!debugSkill.value) return
  if (!execNLQuery.value.trim()) {
    ElMessage.warning('请输入调用指令')
    return
  }
  const userQuery = execNLQuery.value.trim()
  pushHistory(nlHistory, nlHistoryIdx, userQuery, 'nl')
  execRunning.value = true
  execPhase.value = 'thinking'
  execAbortController = new AbortController()
  const assistantIdx = startExecMessage(userQuery)
  let scriptChanged = false
  let streamOk = false

  let result: any = null
  try {
    const token = localStorage.getItem('access_token')
    const history = debugMessages.value.slice(0, assistantIdx - 1).map(m => ({
      role: m.role,
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[执行结果: ${m.runResult.success ? '成功' : '失败'}]` + (m.runResult.error ? ` 错误: ${m.runResult.error}` : '') : '') + (m.scriptUpdated ? `\n\n[脚本已更新: ${m.scriptUpdated}]` : ''),
    }))
    const response = await fetch(`/api/v1/skills/${debugSkill.value.id}/debug-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        message: userQuery + '\n\n（只执行不修改代码，直接用当前脚本运行）',
        history,
        script_name: debugScriptName.value,
        datasource_id: cmdExampleDsName.value
          ? datasources.value.find((d: any) => d.name === cmdExampleDsName.value)?.id
          : undefined,
        table_name: cmdExampleTableName.value || undefined,
        context: {
          exec_tab: 'nl',
          nl_query: userQuery,
          datasource_name: cmdExampleDsName.value || '',
          table_name: cmdExampleTableName.value || '',
          skill_params: skillParams.value || [],
        },
      }),
      signal: execAbortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const scriptChangedRef = { value: false }
    const sseResult = await readDebugSSEStream(response, assistantIdx, scriptChangedRef)
    result = sseResult.result
    scriptChanged = scriptChangedRef.value
    streamOk = sseResult.streamOk
  } catch (e: any) {
    if (e.name === 'AbortError') {
      result = { success: false, error: '已停止' }
    } else {
      result = {
        success: false,
        error: e.response?.data?.detail || (e.message === 'network error' || e.message === 'Failed to fetch' ? '连接异常，请检查后端是否正常运行' : e.message) || String(e),
      }
    }
  } finally {
    execRunning.value = false
    execPhase.value = 'idle'
    execAbortController = null
    const _msg = debugMessages.value[assistantIdx]
    if (_msg && _msg.executingMsgs && _msg.executingMsgs.length > 0) {
      archiveExecutingMsg(_msg)
    }
    if (result && _msg) {
      _msg.runResult = result
      if (!_msg.content) _msg.content = result?.success ? '执行完成' : '执行失败'
    }
  }

  // 脚本被 AI 更新后，自动重新执行
  if (scriptChanged && streamOk && debugSkill.value) {
    const assistantMsg = debugMessages.value[assistantIdx]
    const hasRunResult = assistantMsg?.runResult
    if (!hasRunResult && execNLQuery.value.trim()) {
      if (assistantMsg) {
        assistantMsg.content += '\n\n> 脚本已更新，正在重新执行技能…'
      }
      await handleRunSkillNL()
    }
  }
}

async function handleRunCmd() {
  if (!debugSkill.value) return
  const cmd = execCmdStr.value.trim()
  if (!cmd) {
    ElMessage.warning('请输入命令')
    return
  }
  pushHistory(cmdHistory, cmdHistoryIdx, cmd, 'cmd')

  let parameters: Record<string, any> = {}
  let datasourceName = ''
  let tableName = ''

  if (cmd.startsWith('/')) {
    const parts = cmd.split(/\s+/)
    for (let i = 1; i < parts.length; i++) {
      const eq = parts[i].indexOf('=')
      if (eq > 0) {
        const key = parts[i].slice(0, eq)
        const val = parts[i].slice(eq + 1)
        if (key === 'datasource') {
          datasourceName = val
        } else if (key === 'table' || key === 'tables') {
          tableName = val
        } else {
          try {
            parameters[key] = JSON.parse(val)
          } catch {
            parameters[key] = val
          }
        }
      }
    }
  } else {
    ElMessage.error('命令格式错误，请以 / 开头，例如 /filter condition="age>18"')
    return
  }

  let dsId: string | undefined
  if (datasourceName) {
    const ds = datasources.value.find((d: any) => d.name === datasourceName)
    if (ds) dsId = ds.id
  }

  execRunning.value = true
  execPhase.value = 'executing'
  execAbortController = new AbortController()
  const assistantIdx = startExecMessage(cmd, '正在执行技能脚本...')
  let scriptChanged = false
  let streamOk = false

  let result: any = null
  try {
    const token = localStorage.getItem('access_token')
    const history = debugMessages.value.slice(0, assistantIdx - 1).map(m => ({
      role: m.role,
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[执行结果: ${m.runResult.success ? '成功' : '失败'}]` + (m.runResult.error ? ` 错误: ${m.runResult.error}` : '') : '') + (m.scriptUpdated ? `\n\n[脚本已更新: ${m.scriptUpdated}]` : ''),
    }))
    const response = await fetch(`/api/v1/skills/${debugSkill.value.id}/debug-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        message: cmd,
        history,
        script_name: debugScriptName.value,
        datasource_id: dsId,
        table_name: tableName || undefined,
        context: {
          exec_tab: 'cmd',
          cmd_str: cmd,
          parsed_parameters: parameters,
          datasource_name: datasourceName,
          table_name: tableName,
          skill_params: skillParams.value || [],
        },
      }),
      signal: execAbortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const scriptChangedRef = { value: false }
    const sseResult = await readDebugSSEStream(response, assistantIdx, scriptChangedRef)
    result = sseResult.result
    scriptChanged = scriptChangedRef.value
    streamOk = sseResult.streamOk
  } catch (e: any) {
    if (e.name === 'AbortError') {
      result = { success: false, error: '已停止' }
    } else {
      result = {
        success: false,
        error: e.response?.data?.detail || (e.message === 'network error' || e.message === 'Failed to fetch' ? '连接异常，请检查后端是否正常运行' : e.message) || String(e),
      }
    }
  } finally {
    execRunning.value = false
    execPhase.value = 'idle'
    execAbortController = null
    const _msg = debugMessages.value[assistantIdx]
    if (_msg && _msg.executingMsgs && _msg.executingMsgs.length > 0) {
      archiveExecutingMsg(_msg)
    }
    if (result && _msg) {
      _msg.runResult = result
      if (!_msg.content) _msg.content = result?.success ? '执行完成' : '执行失败'
    }
  }

  if (scriptChanged && streamOk && debugSkill.value) {
    const assistantMsg = debugMessages.value[assistantIdx]
    const hasRunResult = assistantMsg?.runResult
    if (!hasRunResult && execCmdStr.value.trim()) {
      if (assistantMsg) {
        assistantMsg.content += '\n\n> 脚本已更新，正在重新执行…'
      }
      await handleRunCmd()
    }
  }
}

// Chat 调试面板
function handleDebugKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleDebugSend()
    return
  }
  onHistoryKey(e, chatHistory, chatHistoryIdx, debugInput, chatDraft)
}

function handleNLKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleRunSkillNL()
    return
  }
  onHistoryKey(e, nlHistory, nlHistoryIdx, execNLQuery, nlDraft)
}

function handleCmdKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleRunCmd()
    return
  }
  onHistoryKey(e, cmdHistory, cmdHistoryIdx, execCmdStr, cmdDraft)
}

function stopDebugGeneration() {
  if (debugAbortController) {
    debugAbortController.abort()
  }
}

async function handleDebugSend() {
  if (!debugSkill.value || !debugInput.value.trim() || debugStreaming.value) return

  const userMsg = debugInput.value.trim()
  pushHistory(chatHistory, chatHistoryIdx, userMsg, 'chat')
  debugMessages.value.push({ role: 'user', content: userMsg, created_at: new Date().toISOString() })
  debugInput.value = ''
  debugStreaming.value = true
  debugAbortController = new AbortController()

  const assistantIdx = debugMessages.value.length
  debugMessages.value.push({ role: 'assistant', content: '', llmContent: '', thinking: '', thinkingOpen: false, created_at: new Date().toISOString() })
  skillPinnedToBottom.value = true
  nextTick(() => scrollSkillDebugToBottom(true))

  let scriptChanged = false
  let streamOk = false

  try {
    const token = localStorage.getItem('access_token')
    const history = debugMessages.value.slice(0, assistantIdx - 1).map(m => ({
      role: m.role,
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[执行结果: ${m.runResult.success ? '成功' : '失败'}]` + (m.runResult.error ? ` 错误: ${m.runResult.error}` : '') : '') + (m.scriptUpdated ? `\n\n[脚本已更新: ${m.scriptUpdated}]` : ''),
    }))

    const response = await fetch(`/api/v1/skills/${debugSkill.value.id}/debug-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        message: userMsg,
        history,
        script_name: debugScriptName.value,
        datasource_id: cmdExampleDsName.value
          ? datasources.value.find((d: any) => d.name === cmdExampleDsName.value)?.id
          : undefined,
        table_name: cmdExampleTableName.value || undefined,
        context: {
          exec_tab: execTab.value,
          nl_query: execNLQuery.value || '',
          cmd_str: execCmdStr.value || '',
          datasource_name: cmdExampleDsName.value || '',
          table_name: cmdExampleTableName.value || '',
          skill_params: skillParams.value || [],
        },
      }),
      signal: debugAbortController.signal,
    })

    if (!response.ok) {
      const errText = await response.text()
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const scriptChangedRef = { value: false }
    const sseResult = await readDebugSSEStream(response, assistantIdx, scriptChangedRef)
    let result: any = sseResult.result
    scriptChanged = scriptChangedRef.value
    streamOk = sseResult.streamOk
    if (result) {
      const msg = debugMessages.value[assistantIdx]
      msg.runResult = result
    }
  } catch (e: any) {
    if (e.name === 'AbortError') {
      const msg = debugMessages.value[assistantIdx]
      if (msg.content) {
        msg.content += '\n\n*[已停止生成]*'
      } else {
        msg.content = '*[已停止生成]*'
      }
    } else {
      const msg = debugMessages.value[assistantIdx]
      const errHint = `⚠ 连接已断开: ${e.message || String(e)}`
      msg.content = msg.content ? `${msg.content}\n\n${errHint}` : errHint
    }
  } finally {
    const _msg = debugMessages.value[assistantIdx]
    if (_msg && _msg.executingMsgs && _msg.executingMsgs.length > 0) {
      archiveExecutingMsg(_msg)
    }
    debugStreaming.value = false
    debugAbortController = null
    await nextTick()
    scrollSkillDebugToBottom()
  }

  // 脚本被 AI 更新后，自动重新执行一次技能，便于直接查看运行结果
  if (scriptChanged && streamOk && debugSkill.value) {
    const assistantMsg = debugMessages.value[assistantIdx]
    const hasRunResult = assistantMsg?.runResult
    if (!hasRunResult) {
      if (execNLQuery.value.trim()) {
        if (assistantMsg) {
          assistantMsg.content += '\n\n> 脚本已更新，正在用自然语言重新执行技能…'
        }
        await handleRunSkillNL()
      } else if (assistantMsg) {
        assistantMsg.content += '\n\n> 脚本已更新。在左侧执行面板输入参数后执行，即可查看运行结果。'
      }
    }
  }
}

onMounted(() => {
  loadSkills()
  loadDatasources()
  loadAgentConfig()
})
</script>

<style lang="scss" scoped>
.history-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.skill-page {
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  gap: 12px;
  flex-wrap: wrap;
  
  .toolbar-left {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  
  .toolbar-right {
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
}

.op-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
  align-items: stretch;
}

.skill-card {
  height: 100%;
  display: flex;
  flex-direction: column;

  :deep(.el-card__header) { flex-shrink: 0; }
  :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    .skill-name {
      font-weight: 600;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
  .skill-desc {
    color: #666;
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .skill-meta {
    margin: 8px 0;
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    min-height: 26px;
  }
  .skill-actions {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: auto;
    padding-top: 12px;

    .skill-actions-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 4px;
      align-items: center;

      .el-button {
        margin-left: 0;
        padding: 5px 8px;
        font-size: 12px;
      }
    }
  }
}

.upload-text {
  margin-top: 12px;
  color: #909399;
}

// Detail Dialog
.detail-container {
  padding: 0 4px;
  max-height: calc(92vh - 60px);
  overflow-y: auto;
}

.gen-msg-list {
  max-height: calc(92vh - 280px);
  overflow-y: auto;
  padding: 4px 0;
}

.detail-preview-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.md-editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.nl-modify-section {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 16px;

  .nl-modify-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 12px;

    .nl-modify-title {
      font-weight: 600;
      font-size: 15px;
      color: #303133;
    }

    .nl-modify-hint {
      font-size: 12px;
      color: #909399;
    }
  }

  .nl-modify-input-row {
    display: flex;
    gap: 12px;
    align-items: flex-start;

    .nl-modify-input {
      flex: 1;
    }

    .el-button {
      flex-shrink: 0;
      margin-top: 0;
    }
  }

  .modify-error {
    margin-top: 10px;
  }

  .modify-thinking-box {
    margin-top: 12px;
    background: #fff;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    overflow: hidden;

    .modify-thinking-header {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      background: #ecf5ff;
      border-bottom: 1px solid #e4e7ed;
      font-size: 13px;
      color: #409eff;

      .thinking-spin {
        animation: rotate 1.2s linear infinite;
      }

      .modify-thinking-title {
        font-weight: 500;
      }
    }

    .modify-thinking-content {
      padding: 10px 12px;
      font-size: 13px;
      color: #606266;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 260px;
      overflow-y: auto;
    }

    .modify-thinking-placeholder {
      padding: 10px 12px;
      font-size: 13px;
      color: #c0c4cc;
    }

    .modify-content-preview {
      border-top: 1px solid #e4e7ed;
      .modify-content-label {
        padding: 6px 12px 2px;
        font-size: 12px;
        font-weight: 600;
        color: #67c23a;
      }
      pre {
        margin: 0;
        padding: 4px 12px 10px;
        font-size: 12px;
        color: #606266;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 260px;
        overflow-y: auto;
      }
    }
  }
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.detail-tabs {
  :deep(.el-tabs__header) {
    position: sticky;
    top: 0;
    background: #fff;
    z-index: 10;
  }
}

// Scripts
.scripts-header {
  margin-bottom: 8px;
  color: #909399;
  font-size: 13px;
}

.scripts-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.script-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;

  .script-item-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    cursor: pointer;
    background: #fafafa;
    &:hover { background: #f0f2f5; }
    .script-name {
      font-family: 'Consolas', monospace;
      font-size: 13px;
      font-weight: 500;
      flex: 1;
    }
    .script-size {
      font-size: 12px;
      color: #909399;
    }
  }

  .script-body {
    padding: 8px 12px 12px;
    border-top: 1px solid #ebeef5;
  }

  .script-editor {
    width: 100%;
    height: 300px;
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 13px;
    line-height: 1.5;
    border: 1px solid #dcdfe6;
    border-radius: 6px;
    padding: 12px;
    resize: vertical;
    background: #ffffff;
    color: #303133;
    outline: none;
    &:focus { border-color: #409eff; }
  }

  .script-actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
}

// Debug Layout
.debug-layout {
  display: flex;
  gap: 16px;
  height: calc(92vh - 60px);
}

.debug-left {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  gap: 8px;

  .el-tabs { margin: 0; }
}

.debug-section-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
  color: #303133;
}

.debug-right {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  background: #f9fafb;
}

.debug-chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid #ebeef5;
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  background: #fff;
}

.cmd-input-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nl-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  margin-bottom: 10px;
  background: #f0f9ff;
  border: 1px solid #b3d8ff;
  border-radius: 4px;
  font-size: 13px;
  color: #409eff;
  line-height: 1.5;
  
  .el-icon {
    font-size: 16px;
    flex-shrink: 0;
  }
}

.nl-examples {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 6px 10px;
  margin-bottom: 8px;

  .nl-examples-title {
    font-size: 11px;
    color: #909399;
    margin-bottom: 4px;
  }

  .nl-example-item {
    padding: 6px 10px;
    cursor: pointer;
    border-radius: 3px;
    transition: background 0.2s;
    line-height: 1.5;

    &:hover {
      background: #ecf5ff;
    }

    .nl-example-text {
      font-size: 13px;
      color: #606266;
    }
  }
}

.cmd-examples {
  background: #fafafa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 6px 10px;
  margin-bottom: 8px;

  .cmd-examples-title {
    font-size: 11px;
    color: #909399;
    margin-bottom: 4px;
  }

  .cmd-example-item {
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 3px;
    margin-bottom: 4px;
    transition: background 0.2s;
    display: flex;
    flex-direction: column;
    gap: 2px;

    &:hover { background: #ecf5ff; }

    code {
      font-family: 'Consolas', 'Monaco', monospace;
      font-size: 12px;
      color: #409eff;
      white-space: pre-wrap;
      word-break: break-all;
      line-height: 1.4;
    }

    .cmd-example-desc {
      font-size: 11px;
      color: #909399;
    }
  }
}


.cmd-parse-hint {
  margin-top: 8px;
  
  .el-tag {
    white-space: pre-wrap;
    word-break: break-all;
    line-height: 1.4;
    height: auto;
    padding: 4px 8px;
  }
}

.exec-thinking-box {
  margin-top: 16px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;

  .exec-thinking-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    background: #ecf5ff;
    border-bottom: 1px solid #e4e7ed;
    font-size: 13px;
    color: #409eff;

    .thinking-spin { animation: rotate 1.2s linear infinite; }
    .exec-thinking-title { font-weight: 500; }
  }

  .exec-thinking-content {
    padding: 10px 12px;
    font-size: 13px;
    color: #606266;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 260px;
    overflow-y: auto;
  }

  .exec-thinking-placeholder {
    padding: 10px 12px;
    font-size: 13px;
    color: #c0c4cc;
  }
}

.exec-result {
  .exec-result-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }
  .exec-time { font-size: 12px; color: #909399; }
  .exec-label { font-size: 12px; color: #909399; margin-bottom: 4px; }

  .exec-error-block {
    background: #fef0f0;
    border: 1px solid #fde2e2;
    border-radius: 6px;
    padding: 10px;
    pre { margin: 0; font-size: 12px; color: #f56c6c; white-space: pre-wrap; word-break: break-all; }
  }
  .exec-stdout-block {
    background: #f5f7fa;
    border: 1px solid #e4e7ed;
    border-radius: 6px;
    padding: 10px;
    margin-bottom: 8px;
    pre { margin: 0; font-size: 12px; white-space: pre-wrap; }
  }
  .exec-result-block {
    background: #f0f9eb;
    border: 1px solid #e1f3d8;
    border-radius: 6px;
    padding: 10px;
    pre {
      margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-all;
      max-height: 300px; overflow-y: auto;
    }
  }
}

// Chat Panel
.debug-message-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.debug-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 8px;
  color: #c0c4cc;

  p {
    font-size: 14px;
    text-align: center;
    line-height: 1.6;
    padding: 0 12px;
  }
}

.debug-message {
  display: flex;
  gap: 8px;
  max-width: 100%;
  min-width: 0;

  &.user {
    flex-direction: row-reverse;

    .debug-msg-user {
      background: #409eff;
      color: #fff;
      border-radius: 10px 10px 2px 10px;
      padding: 6px 12px;
      font-size: 13px;
      line-height: 1.5;
      word-break: break-word;
      overflow-wrap: break-word;
      max-width: 85%;
      width: fit-content;
    }
    .debug-msg-time {
      font-size: 11px;
      color: #999;
      margin-top: 2px;
    }
  }

  &.assistant {
    align-self: stretch;
    max-width: 100%;

    .debug-msg-assistant {
      background: #fff;
      border: 1px solid #e4e7ed;
      border-radius: 10px 10px 10px 2px;
      padding: 8px 12px;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      overflow-wrap: break-word;
      word-break: break-word;

      :deep(.el-collapse) {
        border-top: none;
        border-bottom: none;
      }
      :deep(.el-collapse-item__header) {
        border-bottom: none;
        padding: 0;
        height: 28px;
        line-height: 28px;
        font-size: 12px;
      }
      :deep(.el-collapse-item__wrap) {
        border-bottom: none;
        background: transparent;
      }
      :deep(.el-collapse-item__content) {
        padding: 0;
      }
    }
  }
}

.debug-msg-avatar {
  flex-shrink: 0;
}

.debug-msg-body {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.debug-message.user .debug-msg-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.debug-msg-thinking {
  margin-bottom: 8px;
  border: 1px solid #d9ecff;
  border-radius: 6px;
  overflow: hidden;
  background: #ecf5ff;

  .thinking-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #409eff;
    font-weight: 500;
    position: sticky;
    top: 0;
    z-index: 10;
    background: #f5f7fa;
    border-bottom: 1px solid #d9ecff;
    cursor: pointer;
    user-select: none;

    .thinking-spin { animation: rotate 1.2s linear infinite; }
    .thinking-toggle { transition: transform 0.2s; }
    .thinking-toggle.open { transform: rotate(90deg); }
    .thinking-model { margin-left: 8px; font-size: 11px; color: #909399; font-weight: normal; }
  }

  .thinking-body {
    padding: 10px 12px;
    font-size: 13px;
    color: #606266;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 300px;
    overflow-y: auto;
  }
}

.debug-msg-executing {
  padding: 6px 0;
  font-size: 13px;
  color: #909399;

  .executing-line {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 2px 0;
  }

  .thinking-spin {
    animation: rotate 1.2s linear infinite;
  }

  .executing-dot {
    color: #67c23a;
    font-size: 14px;
  }
}

.debug-msg-content {
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: break-word;
  word-break: break-word;

  :deep(pre) {
    white-space: pre-wrap;
    word-break: break-all;
    overflow-x: auto;
    max-width: 100%;
  }

  :deep(table) {
    width: 100%;
    table-layout: fixed;
    word-break: break-all;
  }

  :deep(code) {
    white-space: pre-wrap;
    word-break: break-all;
  }
}

.debug-msg-runresult {
  margin-top: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;

  :deep(.el-collapse) {
    border-top: none;
    border-bottom: none;
  }

  .runresult-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: #f5f7fa;
    border-bottom: 1px solid #e4e7ed;
  }

  .exec-time {
    font-size: 11px;
    color: #909399;
  }

  /* 所有 debug 折叠区域统一样式 */
  .debug-msg-assistant :deep(.el-collapse-item__header) {
    position: relative;
    height: 32px;
    line-height: 32px;
    padding: 0 10px;
    font-size: 12px;
    background: #f5f7fa;
    border-bottom: 1px solid #e4e7ed;
  }
  .collapse-label {
    color: #909399;
    font-size: 12px;
  }
  .collapse-copy-btn {
    margin-left: auto;
    padding: 2px 6px;
    font-size: 12px;
  }

  .msg-copy-btn {
    padding: 2px 4px;
    font-size: 12px;
    color: #909399;
    &:hover { color: #409eff; }
  }
  .debug-msg-user .msg-copy-btn { margin-left: 8px; vertical-align: middle; }
  .thinking-header .msg-copy-btn { margin-left: auto; }
  .inspection-header .msg-copy-btn { margin-left: 8px; }
  .inspection-issue-main .msg-copy-btn { margin-left: 8px; }

  .debug-result-error {
    padding: 6px 10px;
    pre {
      margin: 0;
      font-size: 12px;
      color: #f56c6c;
      white-space: pre-wrap;
      word-break: break-all;
    }
  }

  .debug-result-stdout,
  .debug-result-data {
    :deep(.el-collapse-item__header) {
      font-size: 12px;
      height: 28px;
      line-height: 28px;
      padding-left: 10px;
    }
    pre {
      margin: 0;
      font-size: 11px;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 160px;
      overflow-y: auto;
    }
  }
}

.debug-msg-script-updated {
  margin-top: 6px;
}

.debug-msg-inspection {
  margin-top: 8px;
  padding: 10px 12px;
  background: #f0f9eb;
  border-radius: 6px;
  border-left: 3px solid #67c23a;

  .inspection-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;

    .inspection-summary {
      font-size: 13px;
      color: #606266;
    }
  }

  .inspection-issues {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .inspection-issue-item {
    padding: 8px 10px;
    background: rgba(255, 255, 255, 0.5);
    border-radius: 4px;
    font-size: 12px;
    color: #606266;
    line-height: 1.6;

    .inspection-issue-main {
      display: flex;
      align-items: flex-start;
      gap: 6px;
    }

    .inspection-issue-desc {
      flex: 1;
    }

    .inspection-issue-suggestion {
      margin-top: 4px;
      padding-left: 40px;
      color: #909399;
      line-height: 1.6;
    }
  }

  .inspection-error {
    margin-top: 6px;
  }
}

.debug-input-area {
  display: flex;
  gap: 10px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;

  .el-textarea { 
    flex: 1;
    font-size: 14px;
  }
  .el-button { margin-bottom: 4px; }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 6px 0;

  span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #c0c4cc;
    animation: typing 1.4s infinite ease-in-out both;

    &:nth-child(1) { animation-delay: 0s; }
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes typing {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.exp-error-item {
  padding: 8px 12px;
  margin-bottom: 8px;
  background: #fef0f0;
  border-radius: 6px;
  border-left: 3px solid #f56c6c;

  .exp-error-time {
    font-size: 11px;
    color: #909399;
    margin-bottom: 4px;
  }
  .exp-error-msg pre {
    margin: 0;
    font-size: 12px;
    color: #f56c6c;
    white-space: pre-wrap;
    word-break: break-all;
  }
  .exp-error-stdout pre {
    margin: 4px 0 0;
    font-size: 11px;
    color: #909399;
    white-space: pre-wrap;
    word-break: break-all;
  }
}

.exp-positive-item {
  padding: 8px 12px;
  margin-bottom: 8px;
  background: #f0f9eb;
  border-radius: 6px;
  border-left: 3px solid #67c23a;

  .exp-error-time {
    font-size: 11px;
    color: #909399;
    margin-bottom: 4px;
  }
  .exp-error-msg {
    font-size: 12px;
    color: #67c23a;
  }
}
</style>

<style lang="scss">
.markdown-body {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
  padding: 16px 20px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  max-height: 70vh;
  overflow-y: auto;

  h1, h2, h3, h4 { margin-top: 16px; margin-bottom: 8px; font-weight: 600; color: #1d1d1f; }
  h1 { font-size: 22px; border-bottom: 2px solid #409eff; padding-bottom: 6px; }
  h2 { font-size: 19px; border-bottom: 1px solid #e4e7ed; padding-bottom: 4px; }
  h3 { font-size: 16px; }
  p { margin: 8px 0; }
  ul, ol { padding-left: 24px; margin: 8px 0; }
  li { margin: 4px 0; }
  code {
    background: #f0f2f5; padding: 2px 6px; border-radius: 4px;
    font-family: 'Consolas', monospace; font-size: 13px; color: #d63384;
  }
  pre {
    background: #ffffff; border: 1px solid #ebeef5; border-radius: 8px; padding: 14px 18px; overflow-x: auto;
    code { background: none; color: #303133; padding: 0; }
  }
  blockquote {
    border-left: 4px solid #409eff; padding: 8px 16px; margin: 12px 0;
    background: #f0f5ff; color: #606266; border-radius: 0 6px 6px 0;
  }
  table { width: 100%; border-collapse: collapse; margin: 12px 0;
    th, td { border: 1px solid #dcdfe6; padding: 8px 12px; text-align: left; }
    th { background: #f5f7fa; font-weight: 600; }
  }
  a { color: #409eff; }
  hr { border: none; border-top: 1px solid #e4e7ed; margin: 20px 0; }
  strong { font-weight: 600; color: #1d1d1f; }
}
</style>

<style lang="scss" scoped>
.gen-process {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-top: 16px;
  background: #fafbfc;
  overflow: hidden;
}
.gen-process-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  user-select: none;
}
.gen-collapse-icon {
  transition: transform 0.2s;
}
.gen-collapse-rotated {
  transform: rotate(180deg);
}
.gen-process-body {
  padding: 12px 16px;
}
.gen-status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #409eff;
  font-size: 13px;
  margin-bottom: 10px;
}
.gen-spin {
  animation: gen-rotate 1s linear infinite;
}
@keyframes gen-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.gen-log-scroll {
  max-height: 280px;
  overflow-y: auto;
  background: #ffffff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px 14px;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.7;
}
.gen-log-line {
  margin: 2px 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.gen-log-status { color: #67c23a; }
.gen-log-progress { color: #e6a23c; }
.gen-log-chunk { color: #909399; }
.gen-log-error { color: #f56c6c; }
.gen-log-label {
  font-weight: 600;
  margin-right: 6px;
}

.similar-skill-item {
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
  &:last-child { border-bottom: none; }
}
.similar-skill-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.similar-skill-name {
  font-weight: 600;
  font-size: 14px;
}
.similar-skill-score {
  margin-left: auto;
  color: #e6a23c;
  font-size: 13px;
}
.similar-skill-desc {
  color: #606266;
  font-size: 13px;
  margin-bottom: 8px;
  line-height: 1.5;
}
.similar-skill-contact {
  margin-top: 4px;
}
</style>