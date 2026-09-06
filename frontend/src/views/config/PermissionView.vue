<template>
  <div class="permission-container">
    <el-tabs v-model="activeTab">
      <el-tab-pane :label="t('config.permission.grants')" name="grants">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>{{ t('config.permission.grantsManage') }}</span>
              <el-button type="primary" size="small" @click="showGrantDialog = true">
                <el-icon><Share /></el-icon> {{ t('config.permission.addGrant') }}
              </el-button>
            </div>
          </template>

          <div class="filter-bar">
            <el-select v-model="filterType" :placeholder="t('config.permission.resourceType')" clearable style="width: 150px" @change="loadResourcePerms">
              <el-option :label="t('config.permission.typeDatasource')" value="datasource" />
              <el-option :label="t('config.permission.typeOperator')" value="operator" />
              <el-option :label="t('config.permission.typeSkill')" value="skill" />
              <el-option :label="t('config.permission.typeMetadata')" value="metadata" />
            </el-select>
            <el-input v-model="filterResourceId" :placeholder="t('config.permission.resourceIdInput')" clearable style="width: 320px" @keyup.enter="loadResourcePerms" />
            <el-button @click="loadResourcePerms" :disabled="!filterType || !filterResourceId">{{ t('config.permission.queryGrants') }}</el-button>
          </div>

          <el-table :data="resourcePerms" v-loading="loadingPerms" style="width: 100%; margin-top: 16px" :empty-text="t('config.permission.queryHint')">
            <el-table-column prop="user_name" :label="t('common.user')" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.user_name" type="primary" size="small">{{ row.user_name }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="role_name" :label="t('config.permission.roles')" width="120">
              <template #default="{ row }">
                <el-tag v-if="row.role_name" type="warning" size="small">{{ row.role_name }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="permission_level" :label="t('config.permission.permissionLevel')" width="100">
              <template #default="{ row }">
                <el-tag :type="levelColor(row.permission_level)" size="small">{{ levelLabel(row.permission_level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" :label="t('config.permission.grantTime')" width="180" />
            <el-table-column :label="t('common.actions')" width="80">
              <template #default="{ row }">
                <el-button type="danger" size="small" text @click="doRevoke(row)">{{ t('config.permission.revoke') }}</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane :label="t('config.permission.myPermissions')" name="mine">
        <el-card>
          <template #header><span>{{ t('config.permission.myPermissionsTitle') }}</span></template>
          <el-table :data="myPerms" v-loading="loadingMine" style="width: 100%" :empty-text="t('config.permission.noGrantedResources')">
            <el-table-column prop="resource_type" :label="t('config.permission.resourceType')" width="120">
              <template #default="{ row }">{{ typeLabel(row.resource_type) }}</template>
            </el-table-column>
            <el-table-column prop="resource_id" :label="t('config.permission.resourceId')" width="320" show-overflow-tooltip />
            <el-table-column prop="permission_level" :label="t('config.permission.permissionLevel')" width="100">
              <template #default="{ row }">
                <el-tag :type="levelColor(row.permission_level)" size="small">{{ levelLabel(row.permission_level) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="granted_via" :label="t('config.permission.source')" width="100">
              <template #default="{ row }">
                <el-tag :type="row.granted_via === 'role' ? 'warning' : 'primary'" size="small" effect="plain">
                  {{ row.granted_via === 'role' ? t('config.permission.role') : t('config.permission.direct') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" :label="t('config.permission.grantTime')" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane :label="t('config.permission.roleManage')" name="roles">
        <el-card>
          <template #header>
            <div class="card-header">
              <span>{{ t('config.permission.roleManage') }}</span>
              <el-button type="primary" size="small" @click="showRoleDialog = true" v-if="isSuperuser">
                <el-icon><Plus /></el-icon> {{ t('config.permission.createRole') }}
              </el-button>
            </div>
          </template>
          <el-table :data="roles" v-loading="loadingRoles" style="width: 100%" :empty-text="t('config.permission.noRoles')">
            <el-table-column prop="display_name" :label="t('config.permission.roleName')" width="150" />
            <el-table-column prop="name" :label="t('config.permission.identifier')" width="150" />
            <el-table-column prop="description" :label="t('common.description')" />
            <el-table-column prop="member_count" :label="t('config.permission.memberCount')" width="80" />
            <el-table-column :label="t('common.actions')" width="200">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openRoleMembers(row)">{{ t('config.permission.memberManage') }}</el-button>
                <el-button size="small" text type="success" @click="openCopyDialog(row)">{{ t('config.permission.copyToRole') }}</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane :label="t('config.permission.userList')" name="users">
        <el-card>
          <template #header><span>{{ t('config.permission.userList') }}</span></template>
          <el-table :data="users" v-loading="loadingUsers" style="width: 100%" :empty-text="t('config.permission.noUsers')">
            <el-table-column prop="display_name" :label="t('config.permission.username')" width="150" />
            <el-table-column prop="username" :label="t('config.permission.account')" width="150" />
            <el-table-column prop="email" :label="t('config.permission.email')" />
            <el-table-column :label="t('config.permission.roles')" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.is_superuser" type="danger" size="small">{{ t('config.permission.admin') }}</el-tag>
                <el-tag v-else type="info" size="small">{{ t('config.permission.normalUser') }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('common.actions')" width="200">
              <template #default="{ row }">
                <el-button size="small" text type="success" @click="openCopyDialog(row)">{{ t('config.permission.copyToUser') }}</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showGrantDialog" :title="t('config.permission.addGrant')" width="500px">
      <el-form label-width="100px">
        <el-form-item :label="t('config.permission.resourceType')">
          <el-select v-model="grantForm.resource_type" style="width: 100%">
            <el-option :label="t('config.permission.typeDatasource')" value="datasource" />
            <el-option :label="t('config.permission.typeOperator')" value="operator" />
            <el-option :label="t('config.permission.typeSkill')" value="skill" />
            <el-option :label="t('config.permission.typeMetadata')" value="metadata" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('config.permission.resourceId')">
          <el-input v-model="grantForm.resource_id" :placeholder="t('config.permission.resourceUuid')" />
        </el-form-item>
        <el-form-item :label="t('config.permission.grantTarget')">
          <el-radio-group v-model="grantTargetType">
            <el-radio value="user">{{ t('common.user') }}</el-radio>
            <el-radio value="role">{{ t('config.permission.role') }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('config.permission.selectUser')" v-if="grantTargetType === 'user'">
          <el-select v-model="grantForm.user_id" filterable :placeholder="t('config.permission.selectUser')" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('config.permission.selectRole')" v-if="grantTargetType === 'role'">
          <el-select v-model="grantForm.role_id" filterable :placeholder="t('config.permission.selectRole')" style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.display_name" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('config.permission.permissionLevel')">
          <el-select v-model="grantForm.permission_level" style="width: 100%">
            <el-option :label="t('config.permission.viewLevel')" value="view" />
            <el-option :label="t('config.permission.useLevel')" value="use" />
            <el-option :label="t('config.permission.manageLevel')" value="manage" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGrantDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="doGrant" :loading="granting">{{ t('config.permission.grant') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRoleDialog" :title="t('config.permission.createRole')" width="450px">
      <el-form label-width="80px">
        <el-form-item :label="t('common.name')">
          <el-input v-model="roleForm.name" :placeholder="t('config.permission.roleNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('config.permission.displayName')">
          <el-input v-model="roleForm.display_name" :placeholder="t('config.permission.displayNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="t('common.description')">
          <el-input v-model="roleForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRoleDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="doCreateRole" :loading="creatingRole">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showMembersDialog" :title="t('config.permission.roleMembers') + (currentRole?.display_name || '')" width="500px">
      <div style="margin-bottom: 12px; display: flex; gap: 8px;">
        <el-select v-model="newMemberId" filterable :placeholder="t('config.permission.selectUser')" style="flex: 1">
          <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" />
        </el-select>
        <el-button type="primary" @click="doAddMember" :disabled="!newMemberId">{{ t('common.add') }}</el-button>
      </div>
      <el-table :data="roleMembers" style="width: 100%" :empty-text="t('config.permission.noMembers')">
        <el-table-column prop="display_name" :label="t('config.permission.username')" />
        <el-table-column :label="t('common.actions')" width="80">
          <template #default="{ row }">
            <el-button type="danger" size="small" text @click="doRemoveMember(row)">{{ t('config.permission.remove') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="showCopyDialog" :title="t('config.permission.copyPermissions')" width="450px">
      <p style="margin-bottom: 12px; color: #606266;">
        {{ t('config.permission.copyFromPrefix') }} <strong>{{ copySource?.display_name || copySource?.name }}</strong> {{ t('config.permission.copyToSuffix') }}
      </p>
      <el-radio-group v-model="copyTargetType" style="margin-bottom: 12px;">
        <el-radio value="user">{{ t('common.user') }}</el-radio>
        <el-radio value="role">{{ t('config.permission.role') }}</el-radio>
      </el-radio-group>
      <el-select v-if="copyTargetType === 'user'" v-model="copyTargetId" filterable :placeholder="t('config.permission.selectTargetUser')" style="width: 100%">
        <el-option v-for="u in users" :key="u.id" :label="u.display_name" :value="u.id" :disabled="u.id === copySource?.id" />
      </el-select>
      <el-select v-else v-model="copyTargetId" filterable :placeholder="t('config.permission.selectTargetRole')" style="width: 100%">
        <el-option v-for="r in roles" :key="r.id" :label="r.display_name" :value="r.id" :disabled="r.id === copySource?.id" />
      </el-select>
      <template #footer>
        <el-button @click="showCopyDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="doCopy" :loading="copying">{{ t('config.permission.copyPermissions') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Share, Plus } from '@element-plus/icons-vue'
import api from '@/api/index'
import { ElMessage, ElMessageBox } from 'element-plus'

const { t } = useI18n()
const activeTab = ref('grants')
const isSuperuser = ref(false)

const filterType = ref('')
const filterResourceId = ref('')
const resourcePerms = ref<any[]>([])
const loadingPerms = ref(false)

const myPerms = ref<any[]>([])
const loadingMine = ref(false)

const roles = ref<any[]>([])
const loadingRoles = ref(false)

const users = ref<any[]>([])
const loadingUsers = ref(false)

const showGrantDialog = ref(false)
const granting = ref(false)
const grantTargetType = ref('user')
const grantForm = reactive({
  resource_type: 'datasource',
  resource_id: '',
  user_id: '',
  role_id: '',
  permission_level: 'view',
})

const showRoleDialog = ref(false)
const creatingRole = ref(false)
const roleForm = reactive({ name: '', display_name: '', description: '' })

const showMembersDialog = ref(false)
const currentRole = ref<any>(null)
const roleMembers = ref<any[]>([])
const newMemberId = ref('')

const showCopyDialog = ref(false)
const copySource = ref<any>(null)
const copyTargetType = ref('user')
const copyTargetId = ref('')
const copying = ref(false)

function levelColor(level: string) {
  return { view: 'info', use: 'warning', manage: 'danger' }[level] || 'info'
}
function levelLabel(level: string) {
  return { view: t('config.permission.view'), use: t('config.permission.use'), manage: t('config.permission.manage') }[level] || level
}
function typeLabel(type: string) {
  return { datasource: t('config.permission.typeDatasource'), operator: t('config.permission.typeOperator'), skill: t('config.permission.typeSkill'), metadata: t('config.permission.typeMetadata') }[type] || type
}

async function loadMyPerms() {
  loadingMine.value = true
  try {
    myPerms.value = await api.get('/permissions/my-permissions')
  } catch { myPerms.value = [] }
  finally { loadingMine.value = false }
}

async function loadRoles() {
  loadingRoles.value = true
  try {
    roles.value = await api.get('/permissions/roles')
  } catch { roles.value = [] }
  finally { loadingRoles.value = false }
}

async function loadUsers() {
  loadingUsers.value = true
  try {
    users.value = await api.get('/permissions/users')
    isSuperuser.value = users.value.find((u: any) => u.username === localStorage.getItem('username'))?.is_superuser || false
  } catch { users.value = [] }
  finally { loadingUsers.value = false }
}

async function loadResourcePerms() {
  if (!filterType.value || !filterResourceId.value) return
  loadingPerms.value = true
  try {
    resourcePerms.value = await api.get(`/permissions/resource/${filterType.value}/${filterResourceId.value}`)
  } catch {
    resourcePerms.value = []
    ElMessage.error(t('config.permission.queryFailed'))
  }
  finally { loadingPerms.value = false }
}

async function doGrant() {
  granting.value = true
  try {
    await api.post('/permissions/grant', {
      ...grantForm,
      user_id: grantTargetType.value === 'user' ? grantForm.user_id : null,
      role_id: grantTargetType.value === 'role' ? grantForm.role_id : null,
    })
    ElMessage.success(t('config.permission.grantSuccess'))
    showGrantDialog.value = false
    if (filterType.value && filterResourceId.value) loadResourcePerms()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.permission.grantFailed'))
  } finally { granting.value = false }
}

async function doRevoke(row: any) {
  try {
    await ElMessageBox.confirm(t('config.permission.revokeConfirm', { name: row.user_name || row.role_name }), t('common.confirm'), { type: 'warning' })
    await api.post('/permissions/revoke', {
      resource_type: row.resource_type,
      resource_id: row.resource_id,
      user_id: row.user_id || null,
      role_id: row.role_id || null,
      permission_level: row.permission_level,
    })
    ElMessage.success(t('config.permission.revokeSuccess'))
    loadResourcePerms()
  } catch { /* cancelled */ }
}

async function doCreateRole() {
  creatingRole.value = true
  try {
    await api.post('/permissions/roles', roleForm)
    ElMessage.success(t('config.permission.roleCreated'))
    showRoleDialog.value = false
    roleForm.name = ''; roleForm.display_name = ''; roleForm.description = ''
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.permission.createFailed'))
  } finally { creatingRole.value = false }
}

async function openRoleMembers(role: any) {
  currentRole.value = role
  showMembersDialog.value = true
  try {
    roleMembers.value = await api.get(`/permissions/roles/${role.id}/members`)
  } catch { roleMembers.value = [] }
}

async function doAddMember() {
  try {
    await api.post(`/permissions/roles/${currentRole.value.id}/members`, { user_id: newMemberId.value })
    ElMessage.success(t('config.permission.memberAdded'))
    newMemberId.value = ''
    roleMembers.value = await api.get(`/permissions/roles/${currentRole.value.id}/members`)
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.permission.addFailed'))
  }
}

async function doRemoveMember(row: any) {
  try {
    await api.delete(`/permissions/roles/${currentRole.value.id}/members/${row.id}`)
    ElMessage.success(t('config.permission.memberRemoved'))
    roleMembers.value = await api.get(`/permissions/roles/${currentRole.value.id}/members`)
    loadRoles()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.permission.removeFailed'))
  }
}

function openCopyDialog(source: any) {
  copySource.value = source
  copyTargetType.value = 'user'
  copyTargetId.value = ''
  showCopyDialog.value = true
}

async function doCopy() {
  if (!copyTargetId.value) {
    ElMessage.warning(t('config.permission.selectTarget'))
    return
  }
  const isRole = 'member_count' in copySource.value
  copying.value = true
  try {
    const res = await api.post('/permissions/copy', {
      source_user_id: isRole ? '' : copySource.value.id,
      target_user_id: copyTargetType.value === 'user' ? copyTargetId.value : null,
      target_role_id: copyTargetType.value === 'role' ? copyTargetId.value : null,
    })
    ElMessage.success(res.message || t('config.permission.copySuccess'))
    showCopyDialog.value = false
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || t('config.permission.copyFailed'))
  } finally { copying.value = false }
}

onMounted(() => {
  loadMyPerms()
  loadRoles()
  loadUsers()
})
</script>

<style lang="scss" scoped>
.permission-container {
  padding: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}
</style>
