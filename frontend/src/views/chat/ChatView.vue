<template>
  <div class="chat-container">
    <!-- 会话列表侧边栏 -->
    <div class="session-sidebar">
      <el-button class="new-session-btn" @click="handleNewSession">
        <el-icon><Plus /></el-icon> 新建会话
      </el-button>
      <div class="session-list">
        <div
          v-for="session in chatStore.sessions"
          :key="session.id"
          class="session-item"
          :class="{ active: session.id === chatStore.currentSessionId }"
          @click="chatStore.switchSession(session.id)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <span class="session-title">{{ session.title || '新会话' }}</span>
          <el-dropdown trigger="click" @command="(cmd: string) => handleSessionCommand(cmd, session.id)">
            <el-icon class="session-more" @click.stop><MoreFilled /></el-icon>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">重命名</el-dropdown-item>
                <el-dropdown-item command="delete">删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </div>
    </div>

    <!-- 对话主区域 -->
    <div class="chat-main">
      <div v-if="!chatStore.currentSessionId" class="empty-chat">
        <el-icon :size="64" color="#ccc"><ChatDotRound /></el-icon>
        <h2>开始新对话</h2>
        <p>输入自然语言描述，AI将帮你处理数据</p>
      </div>
      <template v-else>
        <!-- 消息流 -->
        <div class="message-list" ref="messageListRef">
          <div
            v-for="msg in chatStore.messages"
            :key="msg.id"
            class="message-item"
            :class="msg.role"
          >
            <div class="message-avatar">
              <el-avatar :size="36" v-if="msg.role === 'assistant'">AI</el-avatar>
              <el-avatar :size="36" v-else>我</el-avatar>
            </div>
            <div class="message-content">
              <div v-if="msg.role === 'assistant'" class="markdown-content" v-html="renderMarkdown(msg.content)"></div>
              <div v-else class="user-text">{{ msg.content }}</div>
              <el-button
                class="copy-btn"
                :icon="CopyDocument"
                circle
                size="small"
                @click="handleCopy(msg.content)"
                title="复制"
              />
            </div>
          </div>
          <div v-if="chatStore.isStreaming && !chatStore.streamingContent" class="message-item assistant">
            <div class="message-avatar"><el-avatar :size="36">AI</el-avatar></div>
            <div class="message-content">
              <div class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="input-area">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            :autosize="{ minRows: 1, maxRows: 6 }"
            placeholder="输入消息... (Enter发送, Shift+Enter换行)"
            @keydown="handleKeyDown"
          />
          <div class="input-actions">
            <el-button
              v-if="chatStore.isStreaming"
              type="danger"
              circle
              @click="chatStore.stopGeneration()"
            >
              <el-icon><VideoPause /></el-icon>
            </el-button>
            <el-button
              v-else
              type="primary"
              circle
              :disabled="!inputText.trim()"
              @click="handleSend"
            >
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'

const chatStore = useChatStore()
const inputText = ref('')
const messageListRef = ref<HTMLElement>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
})

function renderMarkdown(content: string): string {
  return md.render(content)
}

async function handleCopy(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = content
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('已复制到剪贴板')
  }
}

onMounted(() => {
  chatStore.fetchSessions()
})

watch(
  () => chatStore.messages.length,
  () => {
    nextTick(() => {
      if (messageListRef.value) {
        messageListRef.value.scrollTop = messageListRef.value.scrollHeight
      }
    })
  }
)

async function handleNewSession() {
  await chatStore.createSession()
}

async function handleSend() {
  if (!inputText.value.trim()) return
  const text = inputText.value
  inputText.value = ''
  await chatStore.sendMessage(text)
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

async function handleSessionCommand(command: string, sessionId: string) {
  if (command === 'delete') {
    await ElMessageBox.confirm('确定删除此会话？', '提示', { type: 'warning' })
    await chatStore.deleteSession(sessionId)
  } else if (command === 'rename') {
    const { value } = await ElMessageBox.prompt('请输入新名称', '重命名')
    if (value) {
      const { chatApi } = await import('@/api/chat')
      await chatApi.updateSession(sessionId, value)
      await chatStore.fetchSessions()
    }
  }
}
</script>

<style lang="scss" scoped>
.chat-container {
  display: flex;
  height: 100%;
}

.session-sidebar {
  width: 260px;
  background: #f7f7f8;
  border-right: 1px solid #e6e6e6;
  display: flex;
  flex-direction: column;

  .new-session-btn {
    margin: 12px;
  }

  .session-list {
    flex: 1;
    overflow-y: auto;
  }

  .session-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    cursor: pointer;
    border-radius: 8px;
    margin: 2px 8px;

    &:hover, &.active {
      background: #ececec;
    }

    .session-title {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .session-more {
      opacity: 0;
    }

    &:hover .session-more {
      opacity: 1;
    }
  }
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.empty-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;

  h2 { margin: 16px 0 8px; color: #666; }
  p { margin: 0; }
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;

  .copy-btn {
    opacity: 0;
    transition: opacity 0.2s;
    margin-top: 4px;
  }

  &:hover .copy-btn {
    opacity: 1;
  }

  &.user {
    flex-direction: row-reverse;

    .message-content {
      .user-text {
        background: #409eff;
        color: #fff;
        padding: 10px 16px;
        border-radius: 12px;
        max-width: 70%;
        word-break: break-word;
      }
    }
  }

  &.assistant {
    .message-content {
      .markdown-content {
        max-width: 80%;
        line-height: 1.6;

        :deep(pre) {
          background: #1d1d1d;
          color: #f8f8f2;
          padding: 16px;
          border-radius: 8px;
          overflow-x: auto;
        }

        :deep(code) {
          background: #f0f0f0;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 14px;
        }

        :deep(pre code) {
          background: none;
          padding: 0;
        }
      }
    }
  }
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;

  span {
    width: 8px;
    height: 8px;
    background: #999;
    border-radius: 50%;
    animation: typing 1.4s infinite;

    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes typing {
  0%, 60%, 100% { transform: translateY(0); }
  30% { transform: translateY(-8px); }
}

.input-area {
  padding: 16px 20px;
  border-top: 1px solid #e6e6e6;
  display: flex;
  gap: 12px;
  align-items: flex-end;

  .el-textarea {
    flex: 1;
  }

  .input-actions {
    display: flex;
    gap: 8px;
  }
}
</style>
