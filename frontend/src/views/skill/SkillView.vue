<template>
  <div class="skill-page">
    <div class="toolbar">
      <div class="toolbar-left">
        <el-button type="success" @click="showGenerateDialog = true">
          <el-icon><MagicStick /></el-icon>
          {{ t('skill.createSkill') }}
        </el-button>
        <el-button type="primary" @click="showUploadDialog = true">
          <el-icon><Upload /></el-icon>
          {{ t('skill.importSkill') }}
        </el-button>
      </div>
      <div class="toolbar-right">
        <el-select v-model="sortBy" style="width: 120px" @change="loadSkills">
          <el-option :label="t('common.createdAt')" value="created" />
          <el-option :label="t('skill.modifiedAt')" value="updated" />
        </el-select>
        <el-input
          v-model="searchQuery"
          :placeholder="t('skill.searchPlaceholder')"
          style="width: 220px"
          clearable
          :prefix-icon="Search"
        />
      </div>
    </div>

    <div class="skill-sections">
      <div v-for="section in skillSections" :key="section.type" class="skill-section">
        <div class="section-header">
          <span class="section-title">
            <el-icon><component :is="section.icon" /></el-icon>
            {{ section.title }}
          </span>
          <el-tag size="small" :type="section.tagType" round>{{ t('skill.skillCount', { count: section.list.length }) }}</el-tag>
        </div>
        <div class="op-grid">
          <el-card v-for="skill in section.list" :key="skill.id" class="skill-card" shadow="hover">
            <template #header>
              <div class="card-header">
                <span class="skill-name">{{ skill.display_name || skill.name }}</span>
                <el-tag size="small" :type="section.tagType">{{ section.type === 'analysis' ? t('skill.analysis') : t('skill.processing') }}</el-tag>
              </div>
            </template>
            <p class="skill-desc">{{ skill.description || t('skill.noDescription') }}</p>

            <div class="skill-meta">
              <el-tag v-if="skill.scripts?.length" size="small" effect="plain">
                {{ t('skill.scriptCount', { count: skill.scripts.length }) }}
              </el-tag>
              <el-tag v-if="skill.version" size="small" effect="plain">v{{ skill.version }}</el-tag>
            </div>

            <div class="skill-actions">
              <div class="skill-actions-row">
                <el-button size="small" type="primary" @click="openDetail(skill)">
                  <el-icon><Edit /></el-icon> {{ t('common.edit') }}
                </el-button>
                <el-button size="small" type="success" plain @click="openDebug(skill)">
                  <el-icon><VideoPlay /></el-icon> {{ t('common.debug') }}
                </el-button>
                <el-button size="small" @click="openCloneDialog(skill)">
                  <el-icon><CopyDocument /></el-icon> {{ t('common.duplicate') }}
                </el-button>
                <el-button size="small" @click="downloadSkill(skill)">
                  <el-icon><Download /></el-icon> {{ t('common.download') }}
                </el-button>
                <el-button size="small" type="danger" plain @click="confirmDelete(skill)">
                  <el-icon><Delete /></el-icon> {{ t('common.delete') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <el-empty v-if="section.list.length === 0" :description="t('skill.noSkillsInSection', { title: section.title })" />
      </div>
    </div>

    <!-- ==================== 另存为对话框 ==================== -->
    <el-dialog v-model="showCloneDialog" :title="t('skill.saveAs')" width="450px" @closed="cloneName = ''; cloneTarget = null">
      <div v-if="cloneTarget" class="modify-target-info">
        <el-tag>{{ cloneTarget.display_name || cloneTarget.name }}</el-tag>
        <span class="modify-desc">{{ t('skill.cloneHint') }}</span>
      </div>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item :label="t('skill.newName')" required>
          <el-input
            v-model="cloneName"
            :placeholder="t('skill.newNamePlaceholder')"
            @keyup.enter="handleClone"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCloneDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="handleClone" :loading="cloning" :disabled="!cloneName.trim()">
          {{ cloning ? t('skill.cloning') : t('skill.confirmClone') }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== 导入对话框 ==================== -->
    <el-dialog v-model="showUploadDialog" :title="t('skill.importSkill')" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          {{ t('skill.uploadHint') }}
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
        <div class="upload-text">{{ t('skill.dragUploadHint') }}</div>
      </el-upload>
      <template #footer>
        <el-button @click="showUploadDialog = false">{{ t('common.cancel') }}</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 重名冲突对话框 ==================== -->
    <el-dialog v-model="showConflictDialog" :title="t('skill.skillExists')" width="460px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom:16px">
        <template #title>
          {{ t('skill.conflictHint', { name: conflictInfo?.parsed_name }) }}
        </template>
      </el-alert>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item :label="t('skill.newName')">
          <el-input
            v-model="renameValue"
            :placeholder="t('skill.newSkillNamePlaceholder')"
            @keyup.enter="confirmRename"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showConflictDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="danger" plain :loading="importing" @click="confirmOverwrite">{{ t('skill.overwriteExisting') }}</el-button>
        <el-button type="primary" :loading="importing" @click="confirmRename">{{ t('skill.renameImport') }}</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 转流程重名冲突对话框 ==================== -->
    <el-dialog v-model="showPipelineConflict" :title="t('skill.pipelineExists')" width="460px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom:16px">
        <template #title>
          {{ t('skill.pipelineConflictHint', { name: pipelineConflictInfo?.existing_display_name || pipelineConflictInfo?.existing_name }) }}
        </template>
      </el-alert>
      <el-form label-width="80px" style="margin-top: 12px">
        <el-form-item :label="t('skill.newName')">
          <el-input
            v-model="pipelineRenameValue"
            :placeholder="t('skill.newPipelineNamePlaceholder')"
            @keyup.enter="confirmPipelineRename"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPipelineConflict = false">{{ t('common.cancel') }}</el-button>
        <el-button type="danger" plain :loading="convertingPipeline" @click="confirmPipelineOverwrite">{{ t('skill.overwriteCurrent') }}</el-button>
        <el-button type="primary" :loading="convertingPipeline" @click="confirmPipelineRename">{{ t('skill.saveAs') }}</el-button>
      </template>
    </el-dialog>

    <!-- ==================== AI 生成对话框 ==================== -->
    <el-dialog v-model="showGenerateDialog" :title="t('skill.generateSkill')" width="95%" top="2vh" :close-on-press-escape="false" @closed="onGenerateDialogClosed" @opened="scrollListToBottom(genMsgListRef)">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        <template #title>
          {{ t('skill.generateHint') }}
        </template>
      </el-alert>
      <el-form label-width="80px">
        <el-form-item :label="t('skill.requirementDesc')">
          <el-input
            v-model="generatePrompt"
            type="textarea"
            :rows="5"
            :placeholder="t('skill.generatePlaceholderDetailed')"
            :disabled="generating"
            @keydown="onGenHistoryKey"
          />
          <div class="history-tip" v-if="genHistory.length && !generating">
            {{ t('skill.historySwitchHint', { count: genHistory.length }) }}
          </div>
        </el-form-item>
      </el-form>

      <div v-if="genMessages.length" class="gen-msg-list" ref="genMsgListRef">
        <div v-for="(msg, idx) in genMessages" :key="idx" class="debug-message" :class="msg.role">
          <div class="debug-msg-avatar">
            <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
            <el-avatar :size="32" v-else style="background:#67c23a">{{ t('skill.me') }}</el-avatar>
          </div>
          <div class="debug-msg-body">
            <template v-if="msg.role === 'user'">
              <div class="debug-msg-user">{{ msg.content }}</div>
              <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
            </template>
            <div v-else class="debug-msg-assistant">
              <div v-if="msg.thinking" class="debug-msg-thinking">
                <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                  <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                  <span>{{ t('chat.thinking') }}<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
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
        <el-button @click="showGenerateDialog = false" :disabled="generating">{{ t('common.cancel') }}</el-button>
        <el-button v-if="generating" type="danger" @click="stopGenerate">
          <el-icon><VideoPause /></el-icon> {{ t('common.stop') }}
        </el-button>
        <el-button type="primary" @click="handleGenerate" :loading="generating || checkingSimilar" :disabled="generating || checkingSimilar">
          {{ generating ? t('skill.aiGenerating') : (checkingSimilar ? t('skill.checkingSimilar') : t('skill.startGenerate')) }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ==================== 相似技能检测对话框 ==================== -->
    <el-dialog v-model="showSimilarDialog" :title="t('skill.similarSkillsFound')" width="600px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px">
        <template #title>{{ t('skill.similarSkillsHint') }}</template>
      </el-alert>

      <div v-for="skill in similarSkills" :key="skill.id" class="similar-skill-item">
        <div class="similar-skill-header">
          <span class="similar-skill-name">{{ skill.display_name || skill.name }}</span>
          <el-tag v-if="skill.skill_type" size="small">{{ skill.skill_type === 'analysis' ? t('skill.analysisShort') : t('skill.processingShort') }}</el-tag>
          <span class="similar-skill-score">{{ t('skill.similarity') }} {{ (skill.similarity * 100).toFixed(0) }}%</span>
        </div>
        <div class="similar-skill-desc">{{ skill.description || t('skill.noDescriptionParen') }}</div>

        <div v-if="skill.can_use" class="similar-skill-actions">
          <el-button type="primary" size="small" @click="openExistingSkill(skill)">{{ t('skill.viewSkill') }}</el-button>
        </div>
        <div v-else class="similar-skill-contact">
          <el-alert type="info" :closable="false">
            <template #title>
              {{ t('skill.noPermissionHint', { owner: skill.owner_name, email: skill.owner_email }) }}
            </template>
          </el-alert>
        </div>
      </div>

      <template #footer>
        <el-button @click="showSimilarDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="proceedToGenerate">{{ t('skill.stillCreateNew') }}</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 技能详情/修改 Drawer ==================== -->
    <el-dialog
      v-model="detailDrawer"
      :title="detailSkill?.display_name || detailSkill?.name || t('skill.skillDetail')"
      width="95%"
      top="2vh"
      destroy-on-close
      :close-on-press-escape="false"
      class="detail-dialog"
      @opened="scrollListToBottom(modifyMsgListRef)"
    >
      <div v-if="detailSkill" class="detail-container">
        <div class="nl-modify-section">
          <div class="nl-modify-header">
            <span class="nl-modify-title">{{ t('skill.nlModify') }}</span>
            <span class="nl-modify-hint">{{ t('skill.nlModifyHint') }}</span>
          </div>
          <div class="nl-modify-input-row">
            <el-input
              v-model="modifyInstruction"
              type="textarea"
              :rows="2"
              :placeholder="t('skill.modifyPlaceholder')"
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
              {{ t('skill.aiModify') }}
            </el-button>
            <el-button
              v-else
              type="danger"
              @click="modifyAbortCtrl?.abort()"
            >
              <el-icon><VideoPause /></el-icon>
              {{ t('common.stop') }}
            </el-button>
          </div>
          <div v-if="modifyError" class="modify-error">
            <el-alert :title="modifyError" type="error" show-icon :closable="false" />
          </div>
          <div v-if="modifyMessages.length" class="gen-msg-list" ref="modifyMsgListRef">
            <div v-for="(msg, idx) in modifyMessages" :key="idx" class="debug-message" :class="msg.role">
              <div class="debug-msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">AI</el-avatar>
                <el-avatar :size="32" v-else style="background:#67c23a">{{ t('skill.me') }}</el-avatar>
              </div>
              <div class="debug-msg-body">
                <template v-if="msg.role === 'user'">
                  <div class="debug-msg-user">{{ msg.content }}</div>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                </template>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>{{ t('chat.thinking') }}</span>
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

        <div class="detail-preview-label">{{ t('skill.detailPreview') }}</div>

        <el-tabs v-model="detailTab" class="detail-tabs">
          <el-tab-pane label="SKILL.md" name="md">
            <div class="md-editor-toolbar">
              <el-radio-group v-model="mdMode" size="small">
                <el-radio-button value="preview">{{ t('common.preview') }}</el-radio-button>
                <el-radio-button value="edit">{{ t('skill.editMode') }}</el-radio-button>
              </el-radio-group>
              <el-button size="small" type="primary" :loading="savingMd" @click="saveSkillMd">
                <el-icon><Check /></el-icon> {{ t('common.save') }}
              </el-button>
            </div>
            <el-input
              v-if="mdMode === 'edit'"
              v-model="mdEditContent"
              type="textarea"
              :autosize="{ minRows: 12, maxRows: 30 }"
              :placeholder="t('skill.editMdPlaceholder')"
              style="font-family: 'Consolas', 'Monaco', monospace; font-size: 13px"
            />
            <template v-else>
              <div v-if="mdEditContent" class="markdown-body" v-html="renderMarkdown(mdEditContent)"></div>
              <el-empty v-else :description="t('skill.noMdContent')" />
            </template>
          </el-tab-pane>

          <el-tab-pane :label="t('skill.scriptList')" name="scripts">
            <div class="scripts-header">
              <span>{{ t('skill.scriptCount', { count: detailSkill.scripts?.length || 0 }) }}</span>
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
                      <el-icon><Check /></el-icon> {{ t('common.save') }}
                    </el-button>
                    <el-button size="small" type="success" @click="openDebug(detailSkill, script.name)">
                      <el-icon><VideoPlay /></el-icon> {{ t('common.debug') }}
                    </el-button>
                  </div>
                </div>
              </div>
            </div>
            <el-empty v-else :description="t('skill.noScripts')" />
          </el-tab-pane>

          <el-tab-pane :label="t('skill.properties')" name="props">
            <el-descriptions :column="2" border>
              <el-descriptions-item :label="t('skill.name')">{{ detailSkill.name }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.displayName')">{{ detailSkill.display_name }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.type')">
                <div style="display:flex;align-items:center;gap:8px">
                  <el-tag size="small" :type="isAnalysisSkill(detailSkill) ? 'success' : 'primary'">{{ isAnalysisSkill(detailSkill) ? t('skill.analysis') : t('skill.processing') }}</el-tag>
                  <el-select
                    v-model="skillTypeEdit"
                    size="small"
                    style="width:130px"
                    @change="saveSkillType"
                    :loading="savingType"
                  >
                    <el-option :label="t('skill.processing')" value="processing" />
                    <el-option :label="t('skill.analysis')" value="analysis" />
                  </el-select>
                </div>
              </el-descriptions-item>
              <el-descriptions-item :label="t('common.version')">v{{ detailSkill.version }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.visibility')">{{ detailSkill.visibility }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.usageCount')">{{ detailSkill.usage_count }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.storagePath')" :span="2">
                <code>{{ detailSkill.skill_path }}</code>
              </el-descriptions-item>
              <el-descriptions-item :label="t('skill.description')" :span="2">{{ detailSkill.description || '-' }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.tags')" :span="2">
                <el-tag v-for="tag in (detailSkill.tags || [])" :key="tag" size="small" style="margin-right:4px">{{ tag }}</el-tag>
                <span v-if="!detailSkill.tags?.length">-</span>
              </el-descriptions-item>
              <el-descriptions-item :label="t('skill.createdAt')">{{ formatDate(detailSkill.created_at) }}</el-descriptions-item>
              <el-descriptions-item :label="t('skill.updatedAt')">{{ formatDate(detailSkill.updated_at) }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>

          <el-tab-pane :label="t('skill.checkRules')" name="rules">
            <div class="md-editor-toolbar">
              <el-radio-group v-model="rulesMode" size="small">
                <el-radio-button value="preview">{{ t('common.preview') }}</el-radio-button>
                <el-radio-button value="edit">{{ t('skill.editMode') }}</el-radio-button>
              </el-radio-group>
              <el-button size="small" type="primary" :loading="savingRules" @click="saveSkillRules">
                <el-icon><Check /></el-icon> {{ t('common.save') }}
              </el-button>
              <el-button size="small" @click="resetSkillRules">{{ t('skill.clear') }}</el-button>
            </div>
            <div v-if="rulesMode === 'edit'">
              <el-input
                v-model="rulesContent"
                type="textarea"
                :autosize="{ minRows: 12, maxRows: 30 }"
                :placeholder="t('skill.editRulesPlaceholder')"
                style="font-family: 'Consolas', 'Monaco', monospace; font-size: 13px"
              />
            </div>
            <template v-else>
              <div v-if="rulesContent" class="markdown-body" v-html="renderMarkdown(rulesContent)"></div>
              <el-empty v-else :description="t('skill.noSkillRules')" />
            </template>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>

    <!-- ==================== 调试技能 Dialog ==================== -->
    <el-dialog
      v-model="debugDrawer"
      :title="t('skill.aiDebugAssistant') + ': ' + (debugSkill?.display_name || debugSkill?.name || '')"
      width="95%"
      top="2vh"
      destroy-on-close
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :before-close="handleDebugBeforeClose"
      @closed="resetDebug"
      @opened="scrollListToBottom(debugMsgListRef)"
    >
      <div v-if="debugSkill" class="debug-layout">
        <div class="debug-left">
          <div class="debug-section-title"><span>{{ t('skill.inputParams') }}</span></div>
          <el-tabs v-model="execTab">
            <el-tab-pane :label="t('skill.naturalLanguage')" name="nl">
              <div v-if="nlExamples.length" class="nl-examples">
                <div class="nl-examples-title">{{ t('skill.examples') }}</div>
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
                :placeholder="nlPlaceholder + ' (' + t('skill.browseHistory') + ')'"
                @keydown="handleNLKeyDown"
              />
              <el-button v-if="execRunning" type="danger" style="margin-top:10px" @click="stopExec">
                <el-icon><VideoPause /></el-icon> {{ t('common.stop') }}
              </el-button>
              <el-button v-else type="primary" style="margin-top:10px" @click="handleRunSkillNL" :disabled="!execNLQuery.trim() || debugStreaming">
                <el-icon><VideoPlay /></el-icon> {{ t('skill.execute') }}
              </el-button>
            </el-tab-pane>

            <el-tab-pane :label="t('skill.commandLine')" name="cmd">
              <div class="cmd-input-row">
                <div v-if="cmdExamples.length" class="cmd-examples">
                  <div class="cmd-examples-title">{{ t('skill.exampleCommands') }}</div>
                  <div v-for="(ex, i) in cmdExamples" :key="i" class="cmd-example-item" @click="execCmdStr = ex.cmd">
                    <code>{{ ex.cmd }}</code>
                    <span class="cmd-example-desc">{{ ex.desc }}</span>
                  </div>
                </div>

                <el-input v-model="execCmdStr" :placeholder="cmdPlaceholder" type="textarea" :autosize="{ minRows: 18, maxRows: 36 }" size="small" @keydown="handleCmdKeyDown" />
                <div v-if="cmdParseHint" class="cmd-parse-hint">
                  <el-tag size="small" type="info">{{ cmdParseHint }}</el-tag>
                </div>
              </div>
              <el-button v-if="execRunning" type="danger" style="margin-top:10px" @click="stopExec">
                <el-icon><VideoPause /></el-icon> {{ t('common.stop') }}
              </el-button>
              <el-button v-else type="primary" style="margin-top:10px" @click="handleRunCmd" :disabled="!execCmdStr.trim() || debugStreaming">
                <el-icon><VideoPlay /></el-icon> {{ t('skill.execute') }}
              </el-button>
            </el-tab-pane>

          </el-tabs>
        </div>

        <div class="debug-right">
          <div class="debug-chat-header">
            <el-icon><ChatDotRound /></el-icon>
            <span>{{ t('skill.aiDebugTitle') }}</span>
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
              <el-icon><Share /></el-icon> {{ t('skill.convertToPipeline') }}
            </el-button>
            <el-button
              size="small"
              plain
              :loading="expLoading"
              @click="openExperience"
            >
              <el-icon><Document /></el-icon> {{ t('skill.debugExperience') }}
            </el-button>
            <el-button
              size="small"
              plain
              type="danger"
              :disabled="debugStreaming || execRunning || debugMessages.length === 0"
              @click="clearDebugHistory"
            >
              <el-icon><Delete /></el-icon> {{ t('skill.clearHistory') }}
            </el-button>
          </div>
          <div class="debug-message-list" ref="debugMsgListRef" @scroll="onSkillListScroll">
            <div v-if="debugMessages.length === 0 && !execRunning" class="debug-empty">
              <p>{{ t('skill.debugEmptyHint') }}</p>
            </div>
            <div
              v-for="(msg, idx) in debugMessages"
              :key="idx"
              class="debug-message"
              :class="msg.role"
            >
              <div class="debug-msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'assistant'" style="background:#409eff">{{ agentName }}</el-avatar>
                <el-avatar :size="32" v-else style="background:#67c23a">{{ t('skill.me') }}</el-avatar>
              </div>
              <div class="debug-msg-body">
                <template v-if="msg.role === 'user'">
                  <div class="debug-msg-user">
                    {{ msg.content }}
                    <el-button text size="small" @click="copyText(msg.content)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                  </div>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                </template>
                <div v-else class="debug-msg-assistant">
                  <div v-if="msg.thinking" class="debug-msg-thinking">
                    <div class="thinking-header" @click="msg.thinkingOpen = !msg.thinkingOpen">
                      <el-icon class="thinking-toggle" :class="{ open: msg.thinkingOpen }"><CaretRight /></el-icon>
                      <span>{{ t('chat.thinking') }}<span v-if="msg.model" class="thinking-model">{{ msg.model }}</span></span>
                      <el-button text size="small" @click.stop="copyText(msg.thinking)" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                    </div>
                    <div v-show="msg.thinkingOpen" class="thinking-body">{{ msg.thinking }}</div>
                  </div>
                  <el-collapse v-if="msg.content" :model-value="msg._contentOpen === false ? [] : ['content']" @change="(v: any) => { msg._contentOpen = v.length > 0 }">
                    <el-collapse-item name="content">
                      <template #title>
                        <span class="collapse-label">{{ t('skill.aiReply') }}</span>
                        <el-button text size="small" @click.stop="copyText(msg.content)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
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
                  <div v-if="msg.flowEvents && msg.flowEvents.length" class="debug-msg-flow-events">
                    <div v-for="(ev, i) in msg.flowEvents" :key="i" class="flow-event-line">{{ ev }}</div>
                  </div>
                  <el-collapse v-if="msg.stdouts && msg.stdouts.length" model-value="['logs']">
                    <el-collapse-item name="logs">
                      <template #title>
                        <el-icon style="margin-right: 4px;"><Document /></el-icon>
                        <span class="collapse-label">{{ t('skill.processLog') }}</span>
                        <el-button text size="small" @click.stop="copyText(msg.stdouts.join('\n\n'))" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                      </template>
                      <pre class="debug-stdout-archive">{{ msg.stdouts.join('\n\n') }}</pre>
                    </el-collapse-item>
                  </el-collapse>
                  <div class="debug-msg-time" v-if="msg.created_at">{{ formatMsgTime(msg.created_at) }}</div>
                  <div v-if="msg.runResult" class="debug-msg-runresult">
                    <div class="runresult-header">
                      <el-tag :type="msg.runResult.success ? 'success' : 'danger'" size="small">
                        {{ msg.runResult.success ? t('skill.runSuccess') : t('skill.runFailed') }}
                      </el-tag>
                      <span v-if="msg.runResult.execution_time_ms" class="exec-time">{{ msg.runResult.execution_time_ms }}ms</span>
                    </div>
                    <div v-if="msg.runResult.error" class="debug-result-error">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">{{ t('skill.errorInfo') }}</span>
                            <el-button text size="small" @click.stop="copyText(msg.runResult.error)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                          </template>
                          <pre>{{ msg.runResult.error }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.stdout" class="debug-result-stdout">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">{{ t('skill.stdout') }}</span>
                            <el-button text size="small" @click="copyText(msg.runResult.stdout)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                          </template>
                          <pre>{{ msg.runResult.stdout }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                    <div v-if="msg.runResult.result != null" class="debug-result-data">
                      <el-collapse>
                        <el-collapse-item>
                          <template #title>
                            <span class="collapse-label">{{ t('skill.returnData') }}</span>
                            <el-button text size="small" @click.stop="copyText(formatResult(msg.runResult.result))" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                          </template>
                          <pre>{{ formatResult(msg.runResult.result) }}</pre>
                        </el-collapse-item>
                      </el-collapse>
                    </div>
                  </div>
                  <div v-if="msg.inspectionResult" class="debug-msg-inspection">
                    <div class="inspection-header">
                      <el-tag :type="msg.inspectionResult.passed ? 'success' : 'warning'" size="small">
                        {{ msg.inspectionResult.passed ? t('skill.inspectionPassed') : t('skill.inspectionIssues') }}
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
                          <el-button text size="small" @click="copyText(issue.description + (issue.suggestion ? '\n' + t('skill.arrowPrefix') + ' ' + issue.suggestion : ''))" class="msg-copy-btn"><el-icon><CopyDocument /></el-icon></el-button>
                        </div>
                        <div v-if="issue.suggestion" class="inspection-issue-suggestion">{{ t('skill.arrowPrefix') }} {{ issue.suggestion }}</div>
                      </div>
                    </div>
                    <div v-if="msg.inspectionResult.error" class="inspection-error">
                      <el-alert :title="msg.inspectionResult.error" type="warning" :closable="false" />
                    </div>
                  </div>
                  <div v-if="msg.inspectionReport" class="debug-msg-inspection-report">
                    <el-collapse model-value="report">
                      <el-collapse-item name="report">
                        <template #title>
                          <el-icon style="margin-right: 4px;"><CircleCheck /></el-icon>
                          <span class="collapse-label">{{ t('skill.dataInspectionReport') }}</span>
                          <el-button text size="small" @click.stop="copyText(msg.inspectionReport)" class="collapse-copy-btn"><el-icon><CopyDocument /></el-icon> {{ t('common.copy') }}</el-button>
                        </template>
                        <div class="debug-msg-content markdown-body" v-html="renderMarkdown(msg.inspectionReport)"></div>
                      </el-collapse-item>
                    </el-collapse>
                  </div>
                  <div v-if="msg.scriptUpdated" class="debug-msg-script-updated">
                    <el-tag type="warning" size="small">{{ t('skill.scriptUpdatedTag', { name: msg.scriptUpdated }) }}</el-tag>
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
              :placeholder="t('skill.debugInputPlaceholder')"
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

    <el-dialog v-model="showExperience" :title="t('skill.debugExperience')" width="680px">
      <div v-loading="expLoading">
        <el-tabs>
          <el-tab-pane :label="t('skill.inductReasons')">
            <div v-if="experienceData.lessons" class="markdown-body" v-html="renderMarkdown(experienceData.lessons)"></div>
            <el-empty v-else :description="t('skill.noInductedExperience')" :image-size="80" />
          </el-tab-pane>
          <el-tab-pane :label="t('skill.historyErrors') + ' (' + (experienceData.negative || []).length + ')'">
            <div v-if="(experienceData.negative || []).length" style="max-height:400px;overflow-y:auto">
              <div v-for="(err, i) in experienceData.negative" :key="i" class="exp-error-item">
                <div class="exp-error-time">{{ formatTime(err.timestamp) }}</div>
                <div class="exp-error-msg"><pre>{{ err.error_message }}</pre></div>
                <div v-if="err.stdout_preview" class="exp-error-stdout"><pre>{{ err.stdout_preview }}</pre></div>
              </div>
            </div>
            <el-empty v-else :description="t('skill.noErrorRecords')" :image-size="80" />
          </el-tab-pane>
          <el-tab-pane :label="t('skill.successRecords') + ' (' + (experienceData.positive || []).length + ')'">
            <div v-if="(experienceData.positive || []).length" style="max-height:400px;overflow-y:auto">
              <div v-for="(pos, i) in experienceData.positive" :key="i" class="exp-positive-item">
                <div class="exp-error-time">{{ formatTime(pos.timestamp) }}</div>
                <div class="exp-error-msg">{{ pos.result_summary }}</div>
              </div>
            </div>
            <el-empty v-else :description="t('skill.noSuccessRecords')" :image-size="80" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onActivated, watch, nextTick, type Ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Upload, Download, Delete, VideoPlay, CaretRight, Search, Check,
  MagicStick, Edit, CopyDocument, UploadFilled, CaretBottom, Loading,
  Promotion, ChatDotRound, InfoFilled, Share, VideoPause, CircleCheck,
  Document, DataLine, DataAnalysis,
} from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'
import markdownIt from 'markdown-it'
import { formatTime, timePrefix } from '@/utils/time'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const skills = ref<any[]>([])
const searchQuery = ref('')
const sortBy = ref('updated')
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

function applySearch(list: any[]) {
  if (!searchQuery.value) return list
  const q = searchQuery.value.toLowerCase()
  return list.filter(
    (o: any) =>
      (o.name || '').toLowerCase().includes(q) ||
      (o.display_name || '').toLowerCase().includes(q) ||
      (o.description || '').toLowerCase().includes(q)
  )
}

const processingSkills = computed(() => applySearch(skills.value.filter((s: any) => !isAnalysisSkill(s))))
const analysisSkills = computed(() => applySearch(skills.value.filter((s: any) => isAnalysisSkill(s))))
const skillSections = computed(() => [
  { type: 'processing', title: t('skill.processingSkills'), icon: DataLine, tagType: 'primary', list: processingSkills.value },
  { type: 'analysis', title: t('skill.analysisSkills'), icon: DataAnalysis, tagType: 'success', list: analysisSkills.value },
])

const datasources = ref<any[]>([])


async function loadSkills() {
  try {
    skills.value = await api.get(`/skills?sort_by=${sortBy.value}`)
  } catch (e: any) {
    ElMessage.error(t('skill.loadFailed'))
  }
}

async function loadDatasources() {
  try {
    datasources.value = await api.get('/datasources')
  } catch (e: any) {
    /* ignore */
  }
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
    ElMessage.error(t('skill.zipOnly'))
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
    ElMessage.success(t('skill.importedSuccess', { name: res.display_name || res.name }))
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
      ElMessage.error(typeof detail === 'string' ? detail : t('skill.importFailedShort'))
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
    ElMessage.warning(t('skill.nameRequiredShort'))
    return
  }
  await doImport(pendingFile.value, 'rename', renameValue.value.trim())
}

// ==================== 下载 ====================
function isAnalysisSkill(skill: any): boolean {
  if (skill?.skill_type === 'analysis') return true
  const tags: any[] = skill?.tags || []
  return tags.some((t: any) => String(t) === 'skill_type:analysis')
}

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
// 转流程重名冲突
const showPipelineConflict = ref(false)
const pipelineConflictInfo = ref<any>(null)
const pipelineRenameValue = ref('')

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
    ElMessage.error(t('skill.loadExperienceFailed'))
  } finally {
    expLoading.value = false
  }
}

async function convertToPipeline() {
  if (!debugSkill.value || convertingPipeline.value) return
  await streamConvert('skip', null)
}

async function streamConvert(mode: string, newName: string | null) {
  if (!debugSkill.value) return
  convertingPipeline.value = true
  showPipelineConflict.value = false

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
  let existingInfo: any = null

  try {
    const token = localStorage.getItem('access_token')
    const bodyPayload: any = { mode }
    if (mode === 'rename' && newName) {
      bodyPayload.new_name = newName
    }
    const response = await fetch(`/api/v1/pipelines/from-skill-stream/${debugSkill.value.id}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(bodyPayload),
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
        } else if (data.type === 'existing') {
          existingInfo = data
        } else if (data.type === 'done') {
          pipelineName = data.pipeline_name || data.name || t('skill.pipelineDefault')
          streamOk = true
        } else if (data.type === 'error') {
          msg.content += `\n\n` + t('skill.errorMsg', { msg: data.message || data.content || t('skill.unknownError') })
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

    if (existingInfo && !streamOk) {
      // 命中重名，弹窗让用户选择
      pipelineConflictInfo.value = existingInfo
      pipelineRenameValue.value = `${existingInfo.existing_display_name || existingInfo.existing_name} ${t('skill.copySuffix')}`
      showPipelineConflict.value = true
      const msg = debugMessages.value[assistantIdx]
      if (msg) msg.content = t('skill.pipelineExistsHint', { name: existingInfo.existing_display_name || existingInfo.existing_name })
      return
    }

    if (streamOk) {
      const msg = debugMessages.value[assistantIdx]
      if (msg.thinking) msg.thinkingOpen = false
      msg.content = (msg.content || '') + `\n\n` + t('skill.pipelineGenerated', { name: pipelineName })
      ElMessage.success(t('skill.pipelineGenerateSuccess', { name: pipelineName }))
      await loadSkills()
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      const msg = debugMessages.value[assistantIdx]
      if (msg) msg.content = t('skill.convertToPipelineFailed', { error: e.message || String(e) })
    }
  } finally {
    convertingPipeline.value = false
    await nextTick()
    scrollSkillDebugToBottom()
  }
}

// 转流程冲突：覆盖现有
async function confirmPipelineOverwrite() {
  if (!pipelineConflictInfo.value) return
  showPipelineConflict.value = false
  await streamConvert('overwrite', null)
}

// 转流程冲突：另存为
async function confirmPipelineRename() {
  if (!pipelineConflictInfo.value || !pipelineRenameValue.value.trim()) {
    ElMessage.warning(t('skill.newPipelineNameRequired'))
    return
  }
  showPipelineConflict.value = false
  await streamConvert('rename', pipelineRenameValue.value.trim())
}

async function confirmDelete(skill: any) {
  try {
    await ElMessageBox.confirm(
      t('skill.deleteConfirmMsg', { name: skill.display_name || skill.name }),
      t('skill.deleteConfirmTitle'),
      { confirmButtonText: t('common.delete'), cancelButtonText: t('common.cancel'), type: 'warning' }
    )
    await api.delete(`/skills/${skill.id}`)
    ElMessage.success(t('skill.deleteSuccessMsg'))
    await loadSkills()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || t('skill.deleteFailedMsg'))
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
    cloneName.value = (skill.display_name || skill.name) + ' ' + t('skill.copySuffix')
  showCloneDialog.value = true
}

async function handleClone() {
  if (!cloneName.value.trim()) {
    ElMessage.warning(t('skill.nameRequiredShort'))
    return
  }
  if (!cloneTarget.value) return
  cloning.value = true
  try {
    const res = await api.post(`/skills/${cloneTarget.value.id}/clone`, {
      name: cloneName.value.trim(),
    })
    ElMessage.success(t('skill.cloneSuccess', { name: res.display_name || res.name }))
    showCloneDialog.value = false
    cloneName.value = ''
    cloneTarget.value = null
    await loadSkills()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('skill.cloneFailed'))
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
    ElMessage.warning(t('skill.requirementRequired'))
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
            if (thinkingDone && msg.thinking) { msg.thinking += '\n\n' + t('skill.newRoundThinking') + '\n'; msg.thinkingOpen = false; thinkingDone = false }
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
            msg.content += (msg.content ? '\n\n' : '') + t('skill.skillCreatedMsg', { name: skill.display_name || skill.name })
            ElMessage.success(t('skill.skillGeneratedMsg', { name: skill.display_name || skill.name }))
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
        msg.content += '\n\n' + t('skill.generationStopped')
      } else {
        msg.content += `\n\n❌ ${e.message || t('skill.generationFailed')}`
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
const rulesContent = ref('')
const rulesParsed = ref<any>({ std: [], dq: [], sec: [] })
const rulesMode = ref<'preview' | 'edit'>('preview')
const savingRules = ref(false)
const modifyInstruction = ref('')
const modifying = ref(false)
const modifyError = ref('')
const modifyMessages = ref<any[]>([])
const modifyMsgListRef = ref<HTMLElement | null>(null)
const modifyAbortCtrl = ref<AbortController | null>(null)

const expandedScript = ref('')
const scriptContents = reactive<Record<string, string>>({})
const savingScript = ref(false)

const skillTypeEdit = ref('processing')
const savingType = ref(false)

function openDetail(skill: any) {
  detailSkill.value = skill
  mdEditContent.value = skill.skill_md || ''
  modifyInstruction.value = ''
  modifyError.value = ''
  modifyMessages.value = []
  detailTab.value = 'md'
  skillTypeEdit.value = isAnalysisSkill(skill) ? 'analysis' : 'processing'

  Object.keys(scriptContents).forEach(k => delete scriptContents[k])
  expandedScript.value = ''
  for (const s of (skill.scripts || [])) {
    scriptContents[s.name] = ''
  }

  // 加载技能专属规则
  loadSkillRules(skill.id)

  detailDrawer.value = true
}

async function loadSkillRules(skillId: string) {
  rulesContent.value = ''
  rulesParsed.value = { std: [], dq: [], sec: [] }
  try {
    const res = await api.get(`/skills/${skillId}/rules`)
    rulesContent.value = res.data.content || ''
    rulesParsed.value = res.data.parsed || { std: [], dq: [], sec: [] }
  } catch (e) {
    // 静默失败（旧技能无 rules.md）
  }
}

async function saveSkillRules() {
  if (!detailSkill.value) return
  savingRules.value = true
  try {
    await api.put(`/skills/${detailSkill.value.id}/rules`, {
      content: rulesContent.value,
    })
    ElMessage.success(t('skill.skillRulesSaved'))
    // 重新加载解析后的结构
    await loadSkillRules(detailSkill.value.id)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('skill.saveFailedMsg'))
  } finally {
    savingRules.value = false
  }
}

async function resetSkillRules() {
  if (!detailSkill.value) return
  try {
    await ElMessageBox.confirm(t('skill.clearRulesConfirm'), t('skill.tipLabel'), { type: 'warning' })
  } catch {
    return
  }
  try {
    await api.post(`/skills/${detailSkill.value.id}/rules/reset`)
    ElMessage.success(t('skill.rulesCleared'))
    await loadSkillRules(detailSkill.value.id)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('skill.clearFailed'))
  }
}

async function saveSkillType() {
  if (!detailSkill.value) return
  savingType.value = true
  try {
    const newType = skillTypeEdit.value
    const tags = (detailSkill.value.tags || []).filter((t: string) => !String(t).startsWith('skill_type:'))
    tags.push(`skill_type:${newType}`)
    const updated = await api.put(`/skills/${detailSkill.value.id}`, { tags })
    detailSkill.value = { ...detailSkill.value, ...updated }
    const idx = skills.value.findIndex((s: any) => s.id === updated.id)
    if (idx >= 0) skills.value[idx] = { ...skills.value[idx], ...updated }
    ElMessage.success(t('skill.switchedTo' + (newType === 'analysis' ? 'Analysis' : 'Processing')))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('skill.saveFailedMsg'))
    skillTypeEdit.value = isAnalysisSkill(detailSkill.value) ? 'analysis' : 'processing'
  } finally {
    savingType.value = false
  }
}

async function handleModifySkill() {
  if (!detailSkill.value || !modifyInstruction.value.trim()) return
  modifying.value = true
  modifyError.value = ''
  const userText = modifyInstruction.value.trim()
  pushHistory(modifyHistory, modifyHistoryIdx, userText, 'modify')
  modifyMessages.value.push({ role: 'user', content: userText, created_at: new Date().toISOString() })
  modifyMessages.value.push({ role: 'assistant', content: '', thinking: '', thinkingOpen: false, model: '', created_at: new Date().toISOString() })

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
        if (data.type === 'model') {
          msg.model = data.content
        } else if (data.type === 'clear_thinking') {
          msg.thinking = ''; msg.content = ''; msg.thinkingOpen = false; thinkingDone = false
        } else if (data.type === 'thinking') {
          if (thinkingDone && msg.thinking) { msg.thinking += '\n\n' + t('skill.newRoundThinking') + '\n'; msg.thinkingOpen = false; thinkingDone = false }
          if (!msg.thinking) msg.thinkingOpen = false
          msg.thinking = (msg.thinking || '') + data.content
        } else if (data.type === 'content') {
          if (!thinkingDone && msg.thinking) { thinkingDone = true; msg.thinkingOpen = false }
          msg.content += data.content
        } else if (data.type === 'done') {
          doneSkill = data.skill || null
          if (msg.thinking && !thinkingDone) msg.thinkingOpen = false
        } else if (data.type === 'error') {
          errMsg = data.content || t('skill.modifyFailed')
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
      ElMessage.info(t('skill.modifyCancelled'))
    } else if (doneSkill) {
      detailSkill.value = doneSkill
      mdEditContent.value = doneSkill.skill_md || ''
      modifyInstruction.value = ''
      ElMessage.success(t('skill.skillAiModified'))
      await loadSkills()
      if (debugDrawer.value) {
        refreshDebugContext()
      }
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      modifyError.value = e.response?.data?.detail || e.message || t('skill.modifyFailedCheckLlm')
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
      ElMessage.error(t('skill.loadScriptFailed'))
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
    ElMessage.success(t('skill.scriptSaved', { name }))
    detailSkill.value.scripts = await api.get(`/skills/${detailSkill.value.id}/scripts`)
    if (debugDrawer.value) {
      refreshDebugContext()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('skill.saveFailedMsg'))
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
    ElMessage.success(t('skill.mdSaved'))
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('skill.saveFailedMsg'))
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
    ElMessage.warning(t('skill.executingWaitStop'))
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
    content: result?.success ? t('skill.execComplete') : t('skill.execFailed'),
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

const DEBUG_MSG_MAX = 50

function loadSkillDebugMsgs(skillId: string | number): DebugMessage[] {
  try {
    const raw = localStorage.getItem(`dc_skill_debug_msgs_${skillId}`)
    if (!raw) return []
    return JSON.parse(raw).map((m: any) => ({ ...m, thinkingOpen: false, executingMsg: undefined, executingMsgs: undefined }))
  } catch { return [] }
}

function saveSkillDebugMsgs(skillId: string | number, msgs: DebugMessage[]) {
  try {
    const stripped = msgs.slice(-DEBUG_MSG_MAX).map(m => ({ ...m, executingMsg: undefined, executingMsgs: undefined, thinkingOpen: false }))
    localStorage.setItem(`dc_skill_debug_msgs_${skillId}`, JSON.stringify(stripped))
  } catch {
    try {
      const lite = msgs.slice(-DEBUG_MSG_MAX).map(m => ({ role: m.role, content: m.content, llmContent: m.llmContent, scriptUpdated: m.scriptUpdated, model: m.model, created_at: m.created_at }))
      localStorage.setItem(`dc_skill_debug_msgs_${skillId}`, JSON.stringify(lite))
    } catch { /* quota exceeded, give up */ }
  }
}

let _skillDebugSaveTimer: ReturnType<typeof setTimeout> | null = null
let _skillDebugSaveId: string | number | null = null
function scheduleSaveSkillDebug() {
  if (!debugSkill.value) return
  _skillDebugSaveId = debugSkill.value.id
  if (_skillDebugSaveTimer) clearTimeout(_skillDebugSaveTimer)
  _skillDebugSaveTimer = setTimeout(() => {
    if (_skillDebugSaveId != null) saveSkillDebugMsgs(_skillDebugSaveId, debugMessages.value)
  }, 500)
}
function flushSkillDebugSave() {
  if (_skillDebugSaveTimer) {
    clearTimeout(_skillDebugSaveTimer)
    _skillDebugSaveTimer = null
    if (_skillDebugSaveId != null && debugMessages.value.length > 0) saveSkillDebugMsgs(_skillDebugSaveId, debugMessages.value)
  }
}

watch(debugMessages, scheduleSaveSkillDebug, { deep: true })
let debugAbortController: AbortController | null = null
const skillPinnedToBottom = ref(true)

function formatMsgTime(ts?: string): string {
  return formatTime(ts)
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success(t('common.copySuccess'))
  }).catch(() => {
    ElMessage.error(t('common.copyFailed'))
  })
}

function scrollSkillDebugToBottom(force = false) {
  const el = debugMsgListRef.value
  if (!el) return
  if (!force && !skillPinnedToBottom.value) return
  el.scrollTop = el.scrollHeight
}
function scrollListToBottom(el: HTMLElement | null | undefined) {
  if (!el) return
  nextTick(() => { el.scrollTop = el.scrollHeight })
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
  debugMessages.value.push({ role: 'assistant', content: '', llmContent: '', thinking: '', thinkingOpen: false, executingMsgs: initialExecutingMsg ? [`[${timePrefix()}] ${initialExecutingMsg}`] : [], created_at: new Date().toISOString() })
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
    if (!msg.content) msg.content = result?.success ? t('skill.execComplete') : t('skill.execFailed')
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
        msg.thinking += '\n\n' + t('skill.newRoundThinking') + '\n'
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
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'tool_action': {
      msg.toolActions = msg.toolActions || []
      const _taTime = timePrefix()
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
      nextTick(() => scrollSkillDebugToBottom())
      break
    }
    case 'tool_summary': {
      const _tsTime = timePrefix()
      for (const s of (data.summaries || [])) {
        msg.content += (msg.content ? '\n' : '') + `[${_tsTime}] ${s}`
      }
      nextTick(() => scrollSkillDebugToBottom())
      break
    }
    case 'executing':
      execPhase.value = 'executing'
      setExecutingMsg(msg, data.message || t('skill.executingScript'))
      setThinkingDone()
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'progress':
      setExecutingMsg(msg, data.message || '')
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'inspecting':
      archiveExecutingMsg(msg)
      setExecutingMsg(msg, data.message || t('skill.executingInspection'))
      msg.thinkingOpen = false
      state.thinkingDone = true
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'inspection_result':
      msg.inspectionResult = data.result
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'inspection_report':
      msg.inspectionReport = data.report
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'retry':
      archiveExecutingMsg(msg)
      ;(msg.flowEvents = msg.flowEvents || []).push(`[${timePrefix()}] 🔄 ${data.message || t('skill.startFixMsg')}`)
      msg.thinkingOpen = false
      state.thinkingDone = true
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'round':
      archiveExecutingMsg(msg)
      msg.thinkingOpen = false
      state.thinkingDone = true
      msg.content += `\n\n─── ` + t('skill.modifyAttemptRound', { round: data.round, action: data.action === 'execute' ? t('skill.executeAction') : t('skill.modifyAction') }) + ` ───\n`
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'fixing':
      execPhase.value = 'executing'
      archiveExecutingMsg(msg)
      ;(msg.flowEvents = msg.flowEvents || []).push(`[${timePrefix()}] 🔧 ${data.message || t('skill.autoFixingMsg')}`)
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'run_result':
      setThinkingDone()
      archiveExecutingMsg(msg)
      {
        const r = data.result || {}
        const inner = typeof r.result === 'object' && r.result ? r.result : {}
        const failed = !r.success || inner.success === false || (r.error && String(r.error).trim()) || (inner.error && String(inner.error).trim())
        msg.runResult = { ...r, success: !failed, error: r.error || inner.error || '' }
        if (failed) {
          const errMsg = String(r.error || inner.error || t('skill.unknownError')).substring(0, 300)
          msg.content += `\n` + t('skill.execFailedMsg', { error: errMsg }) + `\n`
        } else if (!msg.content) {
          msg.content = t('skill.skillExecComplete')
        }
      }
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'script_updated':
      msg.scriptUpdated = data.script_name
      state.scriptChanged = true
      refreshDebugContext()
      break
    case 'give_up':
      archiveExecutingMsg(msg)
      msg.content += `\n\n` + t('skill.fixFailedContent', { reason: data.reason ? '\n' + data.reason : t('skill.fixFailedDefault') })
      state.result = { success: false, error: data.reason || t('skill.fixFailed') }
      return 'break'
    case 'platform_issue':
      archiveExecutingMsg(msg)
      msg.content += `\n\n` + t('skill.platformIssueContent', { message: data.reason || data.message || '' })
      msg.thinkingOpen = false
      state.thinkingDone = true
      nextTick(() => scrollSkillDebugToBottom())
      break
    case 'fatal': {
      const issues = data.issues || []
      let fatalText = `\n\n` + t('skill.fatalIssueContent', { summary: data.summary || '' }) + `\n`
      for (const issue of issues) {
        fatalText += `\n- [FATAL] ${issue.description || ''}`
        if (issue.suggestion) fatalText += `\n  ` + t('skill.arrowPrefix') + ` ${issue.suggestion}`
      }
      msg.content += fatalText
      state.result = { success: false, error: t('skill.fatalIssueLabel') }
      return 'break'
    }
    case 'warning_confirmation': {
      const issues = data.issues || []
      let warnText = `\n\n` + t('skill.warningConfirmContent', { summary: data.summary || '' }) + `\n`
      for (const issue of issues) {
        warnText += `\n- [WARNING] ${issue.description || ''}`
        if (issue.column) warnText += ` (` + t('skill.columnLabel') + `: ${issue.column})`
        if (issue.suggestion) warnText += `\n  ` + t('skill.arrowPrefix') + ` ${issue.suggestion}`
      }
      warnText += '\n\n> ' + t('skill.fixWarningReply')
      msg.content += warnText
      nextTick(() => scrollSkillDebugToBottom())
      break
    }
    case 'done':
      if (data.result != null) {
        state.result = data.result
      }
      if (!msg.content || msg.content.trim() === '') {
        msg.content = t('skill.debugComplete')
      } else if (!msg.content.includes('✅') && !msg.content.includes('⚠') && !msg.content.includes('🔧') && !msg.content.includes('🚫')) {
        msg.content += '\n\n' + t('skill.debugComplete')
      }
      msg.thinkingOpen = false
      archiveExecutingMsg(msg)
      return 'break'
    case 'error':
      msg.content += `\n\n` + t('skill.errorMsg', { msg: data.content || t('skill.unknownError') })
      state.result = { success: false, error: data.content || t('skill.execFailed') }
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
  // generate history is global (not tied to a specific skill)
  if (key === 'generate') {
    try {
      const raw = localStorage.getItem('dc_skill_history_generate')
      if (raw) return JSON.parse(raw)
      return []
    } catch { return [] }
  }
  if (!_curSkillId) return []
  const newKey = `dc_skill_history_${_curSkillId}_${key}`
  const oldKey = `dc_skill_history_${key}`
  try {
    const raw = localStorage.getItem(newKey)
    if (raw) return JSON.parse(raw)
    // 迁移：旧全局历史被首个打开的技能领走
    const legacy = localStorage.getItem(oldKey)
    if (legacy) {
      const parsed = JSON.parse(legacy)
      localStorage.setItem(newKey, JSON.stringify(parsed))
      localStorage.removeItem(oldKey)
      return parsed
    }
    return []
  } catch {
    return []
  }
}

function saveHistory(key: string, list: string[]) {
  if (key === 'generate') {
    try {
      localStorage.setItem('dc_skill_history_generate', JSON.stringify(list.slice(-HISTORY_MAX)))
    } catch {}
    return
  }
  if (!_curSkillId) return
  try {
    localStorage.setItem(`dc_skill_history_${_curSkillId}_${key}`, JSON.stringify(list.slice(-HISTORY_MAX)))
  } catch {}
}

let _curSkillId = ''
function reloadSkillHistories(skillId: string | number) {
  _curSkillId = String(skillId)
  nlHistory.value = loadHistory('nl')
  cmdHistory.value = loadHistory('cmd')
  chatHistory.value = loadHistory('chat')
  genHistory.value = loadHistory('generate')
  modifyHistory.value = loadHistory('modify')
  nlHistoryIdx.value = -1
  cmdHistoryIdx.value = -1
  chatHistoryIdx.value = -1
  genHistoryIdx.value = -1
  modifyHistoryIdx.value = -1
}

const nlHistory = ref<string[]>([])
const nlHistoryIdx = ref(-1)
const cmdHistory = ref<string[]>([])
const cmdHistoryIdx = ref(-1)
const chatHistory = ref<string[]>([])
const chatHistoryIdx = ref(-1)
const genHistory = ref<string[]>([])
const genHistoryIdx = ref(-1)
const genDraft = ref('')
const modifyHistory = ref<string[]>([])
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
  return t('skill.cmdDefaultPlaceholder', { name })
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
    return t('skill.nlHintClean')
  }
  if (desc.includes('检索') || desc.includes('搜索') || desc.includes('查询')) {
    return t('skill.nlHintSearch')
  }
  if (desc.includes('分析') || desc.includes('统计')) {
    return t('skill.nlHintAnalyze')
  }
  if (desc.includes('导出')) {
    return t('skill.nlHintExport')
  }
  if (desc.includes('采集') || desc.includes('爬取')) {
    return t('skill.nlHintCollect')
  }
  if (desc.includes('转换') || desc.includes('处理')) {
    return t('skill.nlHintTransform')
  }
  return ''
})

const nlPlaceholder = computed(() => {
  if (!debugSkill.value) return t('skill.nlDefaultPlaceholder')
  const examples = nlExamples.value
  if (examples.length > 0) {
    return examples[0]
  }
  const skill = debugSkill.value
  const name = skill.display_name || skill.name || ''
  const desc = skill.description || ''
  const params = skillParams.value
  if (name.includes('文物') || desc.includes('文物')) {
    return t('skill.nlPlaceholderHeritage')
  }
  if (desc.includes('清洗') || desc.includes('去重')) {
    return t('skill.nlPlaceholderClean')
  }
  if (desc.includes('检索') || desc.includes('搜索')) {
    if (params.length > 0) {
      const pExamples = params.slice(0, 2).map((p: any) => {
        if (p.example) return t('skill.nlParamExample', { name: p.name, value: p.example })
        return t('skill.nlParamExampleDefault', { name: p.name })
      })
      return t('skill.nlPlaceholderSearchParam', { params: pExamples.join(', ') })
    }
    return t('skill.nlPlaceholderSearchDefault')
  }
  if (desc.includes('分析') || desc.includes('统计')) {
    return t('skill.nlPlaceholderAnalyze')
  }
  if (desc.includes('导出')) {
    return t('skill.nlPlaceholderExport')
  }
  if (desc.includes('采集')) {
    return t('skill.nlPlaceholderCollect')
  }
  if (params.length > 0) {
    const requiredParams = params.filter((p: any) => p.required)
    if (requiredParams.length > 0) {
      const firstParam = requiredParams[0]
      if (firstParam.example) {
        return t('skill.nlPlaceholderSetParam', { name: firstParam.name, value: firstParam.example })
      }
    }
  }
  return t('skill.nlDefaultPlaceholder')
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
  if (paramKeys.length === 0) return t('skill.skillParamNoParams', { name: skillName })
  return t('skill.skillParamDetail', { name: skillName, params: paramKeys.map(k => `${k}=${params[k]}`).join(', ') })
})

const cmdExamples = computed(() => {
  const name = debugSkill.value?.name || 'skill'
  const params = skillParams.value
  const examples: { cmd: string; desc: string }[] = []
  
  const firstDs = datasources.value?.[0]
  const dsName = cmdExampleDsName.value || firstDs?.name || ''
  const tblName = cmdExampleTableName.value || ''

  function paramValue(p: any): string {
    if (p.is_datasource) return dsName || t('skill.paramValueDsName')
    if (p.is_table) return tblName || t('skill.paramValueTableName')
    if (p.example) return String(p.example)
    if (p.default !== undefined && p.default !== null) return String(p.default)
    if (p.type === 'bool') return 'true'
    if (p.type === 'int' || p.type === 'float') {
      if (p.name.includes('limit') || p.name.includes('count')) return '10'
      if (p.name.includes('max')) return '100'
      return '1'
    }
    if (p.name.includes('path') || p.name.includes('file') || p.name.includes('log')) return './output.log'
    if (p.name.includes('name')) return t('skill.paramValueName')
    if (p.name.includes('id')) return 'ID'
    return t('skill.paramValueValue')
  }

  if (!params.length) {
    examples.push({ cmd: `/${name}`, desc: t('skill.basicCallDesc') })
    examples.push({ cmd: `/${name} param1=value1 param2=value2`, desc: t('skill.paramCallDesc') })
    return examples
  }

  const required = params.filter((p: any) => p.required)
  const optional = params.filter((p: any) => !p.required)

  if (required.length > 0) {
    const requiredPart = required.map((p: any) => `${p.name}=${paramValue(p)}`).join(' ')
    examples.push({ cmd: `/${name} ${requiredPart}`, desc: t('skill.requiredParamDesc') })
  } else {
    examples.push({ cmd: `/${name}`, desc: t('skill.basicCallDesc') })
  }

  const additionalParams = optional.slice(0, 2)
  if (additionalParams.length > 0) {
    const allParams = [...required, ...additionalParams]
    const allPart = allParams.map((p: any) => `${p.name}=${paramValue(p)}`).join(' ')
    examples.push({ cmd: `/${name} ${allPart}`, desc: t('skill.fullParamDesc') })
  }

  return examples
})




async function clearDebugHistory() {
  try {
    await ElMessageBox.confirm(t('skill.clearDebugConfirm'), t('skill.tipLabel'), { type: 'warning' })
  } catch { return }
  if (debugSkill.value) {
    localStorage.removeItem(`dc_skill_debug_msgs_${debugSkill.value.id}`)
  }
  debugMessages.value = []
  ElMessage.success(t('skill.debugHistoryCleared'))
}

function resetDebug() {
  flushSkillDebugSave()
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
  debugMessages.value = loadSkillDebugMsgs(freshSkill.id)
  reloadSkillHistories(freshSkill.id)
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
    ElMessage.warning(t('skill.callInstructionRequired'))
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
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[` + t('skill.execResultLabel') + `: ${m.runResult.success ? t('skill.successLabel') : t('skill.failedLabel')}]` + (m.runResult.error ? ` ` + t('skill.errorMsg', { msg: m.runResult.error }) : '') : '') + (m.scriptUpdated ? `\n\n[` + t('skill.scriptUpdatedLabel', { name: m.scriptUpdated }) + `]` : ''),
    }))
    const response = await fetch(`/api/v1/skills/${debugSkill.value.id}/debug-chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        message: userQuery + '\n\n' + t('skill.execOnlyMsg'),
        history,
        script_name: debugScriptName.value,
        datasource_id: userQuery.includes('数据源')
          ? undefined
          : (cmdExampleDsName.value
            ? datasources.value.find((d: any) => d.name === cmdExampleDsName.value)?.id
            : undefined),
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
      result = { success: false, error: t('skill.stopped') }
    } else {
      result = {
        success: false,
        error: e.response?.data?.detail || (e.message === 'network error' || e.message === 'Failed to fetch' ? t('skill.connectionError') : e.message) || String(e),
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
      if (!_msg.content) _msg.content = result?.success ? t('skill.execComplete') : t('skill.execFailed')
    }
  }

  // 脚本被 AI 更新后，自动重新执行
  if (scriptChanged && streamOk && debugSkill.value) {
    const assistantMsg = debugMessages.value[assistantIdx]
    const hasRunResult = assistantMsg?.runResult
    if (!hasRunResult && execNLQuery.value.trim()) {
      if (assistantMsg) {
        assistantMsg.content += '\n\n> ' + t('skill.scriptUpdatedReexecuting')
      }
      await handleRunSkillNL()
    }
  }
}

async function handleRunCmd() {
  if (!debugSkill.value) return
  const cmd = execCmdStr.value.trim()
  if (!cmd) {
    ElMessage.warning(t('skill.cmdRequired'))
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
    ElMessage.error(t('skill.cmdFormatError'))
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
  const assistantIdx = startExecMessage(cmd, t('skill.executingScript'))
  let scriptChanged = false
  let streamOk = false

  let result: any = null
  try {
    const token = localStorage.getItem('access_token')
    const history = debugMessages.value.slice(0, assistantIdx - 1).map(m => ({
      role: m.role,
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[` + t('skill.execResultLabel') + `: ${m.runResult.success ? t('skill.successLabel') : t('skill.failedLabel')}]` + (m.runResult.error ? ` ` + t('skill.errorMsg', { msg: m.runResult.error }) : '') : '') + (m.scriptUpdated ? `\n\n[` + t('skill.scriptUpdatedLabel', { name: m.scriptUpdated }) + `]` : ''),
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
      result = { success: false, error: t('skill.stopped') }
    } else {
      result = {
        success: false,
        error: e.response?.data?.detail || (e.message === 'network error' || e.message === 'Failed to fetch' ? t('skill.connectionError') : e.message) || String(e),
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
      if (!_msg.content) _msg.content = result?.success ? t('skill.execComplete') : t('skill.execFailed')
    }
  }

  if (scriptChanged && streamOk && debugSkill.value) {
    const assistantMsg = debugMessages.value[assistantIdx]
    const hasRunResult = assistantMsg?.runResult
    if (!hasRunResult && execCmdStr.value.trim()) {
      if (assistantMsg) {
        assistantMsg.content += '\n\n> ' + t('skill.scriptUpdatedReexecutingShort')
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
  // 清理中止后不完整的 assistant 消息（既无执行结果也无脚本更新 → LLM 话说到一半被中止）
  // 保留到下一轮会误导 LLM 重复同样的文字，不调工具直接输出
  const lastMsg = debugMessages.value[debugMessages.value.length - 1]
  if (lastMsg && lastMsg.role === 'assistant' && !lastMsg.runResult && !lastMsg.scriptUpdated) {
    const content = lastMsg.content || ''
    const llmContent = lastMsg.llmContent || ''
    // 只清理"几乎为空"或"只有停止标记"的消息，有实质内容的保留（可能 LLM 已经输出了有用信息）
    const trimmed = (llmContent || content).replace(/\[已停止生成\]/g, '').trim()
    if (!trimmed) {
      debugMessages.value.pop()
    }
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
      content: (m.llmContent != null ? m.llmContent : m.content) + (m.runResult ? `\n\n[` + t('skill.execResultLabel') + `: ${m.runResult.success ? t('skill.successLabel') : t('skill.failedLabel')}]` + (m.runResult.error ? ` ` + t('skill.errorMsg', { msg: m.runResult.error }) : '') : '') + (m.scriptUpdated ? `\n\n[` + t('skill.scriptUpdatedLabel', { name: m.scriptUpdated }) + `]` : ''),
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
        msg.content += '\n\n' + t('skill.generationStopped')
      } else {
        msg.content = t('skill.generationStopped')
      }
    } else {
      const msg = debugMessages.value[assistantIdx]
      const errHint = t('skill.connectionDropped', { error: e.message || String(e) })
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
          assistantMsg.content += '\n\n> ' + t('skill.scriptUpdatedNLReexecuting')
        }
        await handleRunSkillNL()
      } else if (assistantMsg) {
        assistantMsg.content += '\n\n> ' + t('skill.scriptUpdatedHint')
      }
    }
  }
}

onMounted(async () => {
  await loadSkills()
  loadDatasources()
  loadAgentConfig()
  genHistory.value = loadHistory('generate')

  const debugId = route.query.debug as string
  if (debugId) {
    const skill = skills.value.find((s: any) => s.id === debugId)
    const userMessage = route.query.instruction ? decodeURIComponent(route.query.instruction as string) : ''
    const dsName = route.query.ds_name as string || ''
    const tblName = route.query.table_name as string || ''
    const tgtDsName = route.query.target_ds_name as string || ''
    const tgtTblName = route.query.target_table_name as string || ''
    const chatSessionId = route.query.chat_session_id as string || ''
    router.replace({ query: {} })
    if (skill) {
      await openDebug(skill)
      if (dsName) cmdExampleDsName.value = dsName
      if (tblName) cmdExampleTableName.value = tblName
      // 调后端生成技能调用指令（根据技能参数要求 + 对话上下文）
      let instruction = userMessage
      if (chatSessionId && userMessage) {
        try {
          console.log('[infer-instruction] 调用端点:', { skill_id: skill.id, chat_session_id: chatSessionId, user_message: userMessage, dsName, tblName, tgtDsName, tgtTblName })
          const res = await api.post(`/skills/${skill.id}/infer-instruction`, {
            chat_session_id: chatSessionId,
            user_message: userMessage,
            source_datasource_name: dsName || undefined,
            source_data_name: tblName || undefined,
            target_datasource_name: tgtDsName || undefined,
            target_table_name: tgtTblName || undefined,
          })
          console.log('[infer-instruction] 返回:', res)
          if (res?.instruction) instruction = res.instruction
        } catch (e: any) {
          console.error('[infer-instruction] 失败:', e?.message || e, e?.response?.data)
        }
      } else {
        console.log('[infer-instruction] 跳过: chatSessionId=', chatSessionId, 'userMessage=', userMessage)
      }
      if (instruction) {
        console.log('[infer-instruction] 最终指令:', instruction)
        execNLQuery.value = instruction
      }
    }
    return
  }
  if (route.query.create === 'true') {
    const desc = route.query.desc ? decodeURIComponent(route.query.desc as string) : ''
    router.replace({ query: {} })
    generatePrompt.value = desc
    showGenerateDialog.value = true
  }
})

// keep-alive 缓存后再次激活时，onMounted 不触发，用 onActivated 处理 query
onActivated(() => {
  if (route.query.create === 'true') {
    const desc = route.query.desc ? decodeURIComponent(route.query.desc as string) : ''
    router.replace({ query: {} })
    generatePrompt.value = desc
    showGenerateDialog.value = true
  }
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

.skill-sections {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.skill-section {
  .section-header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--el-border-color-lighter);
    .section-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 16px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }
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
  width: 520px;
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

.debug-msg-flow-events {
  padding: 6px 0;
  font-size: 13px;
  color: #606266;

  .flow-event-line {
    padding: 3px 0;
    border-left: 3px solid #409eff;
    padding-left: 8px;
    margin: 2px 0;
  }
}

.debug-stdout-archive {
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 300px;
  overflow-y: auto;
  margin: 0;
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

.debug-msg-inspection-report {
  margin-top: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;

  :deep(.el-collapse) {
    border-top: none;
    border-bottom: none;
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