/**
 * 测试指令 + 预期结果
 *
 * 所有步骤在同一个会话里连续执行，模拟用户真实聊天过程。
 *
 * action 字段说明：
 * - select_data: 出现数据匹配建议时，点"选择此数据"
 * - use_skill: 出现技能/流程匹配建议时，点"使用技能"
 * - continue: 点"继续处理"/"继续分析"
 * - no_suggestion: 不出现建议，等待 Agent 处理完成
 * - verify_skill_page: 跳转到技能调试页面，验证指令并运行
 *
 * operation 字段：描述该步骤的操作，便于理解
 */

export interface TestStep {
  msg: string
  expect: {
    type?: 'analysis' | 'processing' | 'chat'
    keep?: boolean
    matchSkill?: string
    matchPipeline?: string
    noMatch?: boolean
    action?: 'select_data' | 'use_skill' | 'continue' | 'no_suggestion' | 'verify_skill_page'
    operation?: string
  }
}

export interface TestGroup {
  name: string
  steps: TestStep[]
}

export const testGroups: TestGroup[] = [
  {
    name: '数据演进完整流程',
    steps: [
      {
        msg: '帮我查一下在文物库数据源，那个数据表更像合并后的文物信息列表？',
        expect: { type: 'analysis', action: 'select_data', operation: '出现数据匹配建议，选择数据 文物库 → national_key_cultural_relic_protection_units_merged' },
      },
      {
        msg: '我要把这个数据导出一份？可以吗？',
        expect: { type: 'processing', keep: true, action: 'no_suggestion', operation: '提示指定目标数据源，等待 Agent 响应' },
      },
      {
        msg: '导出到 文物列表 数据源',
        expect: { type: 'processing', keep: true, action: 'select_data', operation: '出现目标表匹配建议，不选择数据也不继续处理' },
      },
      {
        msg: '导出到 文物列表 数据源',
        expect: { type: 'processing', keep: true, action: 'use_skill', operation: '出现技能匹配建议 data-etl，点 使用技能 跳转' },
      },
      {
        msg: '',
        expect: { action: 'verify_skill_page', matchSkill: 'data-etl', operation: '出现指令 将 "文物库" 数据源中的 "national_key_cultural_relic_protection_units_merged" 表迁移到 "文物列表" 的 "全国文物" 表，运行调试结果' },
      },
      {
        msg: '再看看文物列表数据源，哪个数据是迁移过来的数据',
        expect: { type: 'analysis', keep: false, action: 'select_data', operation: '出现数据匹配建议，选择数据 文物列表 → 全国文物' },
      },
      {
        msg: '好的，那我们就分析这个数据表',
        expect: { type: 'analysis', keep: true, action: 'no_suggestion', operation: 'Agent 分析数据表结构和内容' },
      },
      {
        msg: '我想把这张表按照地址提取出地级市作为新的一列，可以吗？',
        expect: { type: 'processing', keep: true, action: 'use_skill', operation: '出现技能匹配建议 semantic-classify，点 使用技能 跳转' },
      },
      {
        msg: '',
        expect: { action: 'verify_skill_page', matchSkill: 'semantic-classify', operation: '出现指令 将 "文物列表" 数据源中的 "全国文物" 按照地址列进行语义分类提取出地级市信息，分类结果写入新加列"地级市"，运行调试结果' },
      },
      {
        msg: '统计下Top50的地级市文物数量',
        expect: { type: 'analysis', keep: true, action: 'no_suggestion', operation: 'Agent 统计 Top50 地级市文物数量' },
      },
      {
        msg: '你好',
        expect: { type: 'chat', action: 'no_suggestion', operation: '闲聊，Agent 回复问候' },
      },
    ],
  },
]
