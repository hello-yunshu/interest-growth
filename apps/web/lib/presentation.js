// User-facing presentation vocabulary. Domain/API values stay unchanged at
// the boundary; only this module decides how they appear in the renderer.

const labels = {
  question: { captured: '刚记下', paused: '已暂停', active_topic: '正在探索', closed: '已收束' },
  energy: { light: '轻量', normal: '标准', deep: '深入' },
  mastery: {
    unfamiliar: '还不熟悉', familiar: '已经见过', explain: '可以解释', example: '可以举例',
    distinguish: '能够区分', transfer: '能够迁移', evidence_boundary: '知道证据边界', stable_expression: '表达稳定',
  },
  verification: {
    unverified: '未核验', source_identified: '已定位原始来源', human_verified: '已人工核验',
    invalidated: '已撤销核验', stale: '需要重新核验', pending: '等待核验', verified: '已核验',
  },
  publishability: {
    internal_only: '仅内部学习', limited: '证据有限', supported_with_caution: '可谨慎表达',
    stable: '相对稳定', controversial: '存在争议', not_publishable: '不建议公开',
  },
  task: {
    todo: '待处理', available: '可用', running: '进行中', completed: '已完成', done: '已完成',
    failed: '失败', loading: '加载中', ready: '已就绪', configured: '已配置', optional: '可选',
    enabled: '已启用', disabled: '已停用', on: '开启', off: '关闭', open: '当前打开', saved: '已保存',
    proposed: '待确认', accepted: '已接受', rejected: '已拒绝', active: '进行中', closed: '已结束',
    identity_verified: '身份已确认', identity_unverified: '身份未确认', not_exposed: '未提供',
  },
  severity: { high: '高风险', medium: '中等风险', low: '低风险', critical: '严重风险', warning: '提醒' },
  sourceType: { paper: '论文', book: '书籍', web: '网页', report: '报告', document: '文档', note: '学习笔记', learning_note: '学习笔记', practice: '练习记录', activity: '实践记录' },
  capability: { chat: '对话', deep_question: '深入提问', mastery_path: '学习路径', deep_research: '深入研究', visualize: '可视化' },
  revisionMode: { rewrite: '改写', shorten: '缩短', expand: '展开' },
  activity: {
    stage_start: '开始阶段', stage_end: '阶段完成', progress: '进展', tool_call: '调用工具',
    tool_result: '工具结果', sources: '来源', wait_for_input: '等待你的输入', error: '出错了',
    done: '已完成', session: '学习会话', session_meta: '会话信息', activity: '活动记录',
  },
  connection: {
    Initializing: '正在初始化', Connected: '已连接', Reconnecting: '正在重连', Offline: '已离线',
    LoginExpired: '登录已过期', IdentityChanged: '服务器身份已变化', UpdateRequired: '需要更新',
    UnsupportedServer: '服务器版本不支持', LocalCoreError: '本地服务出错',
  },
  domain: { general: '通用兴趣', psychology: '心理学' },
  platform: { windows: 'Windows', macos: 'macOS', android: 'Android', linux: 'Linux', browser: '浏览器' },
};

export function labelFor(kind, value, fallback = '未知状态') {
  const raw = String(value ?? '').trim();
  if (!raw) return fallback;
  return labels[kind]?.[raw] || fallback;
}

export const questionLabel = value => labelFor('question', value);
export const energyLabel = value => labelFor('energy', value, '标准');
export const masteryLabel = value => labelFor('mastery', value);
export const verificationLabel = value => labelFor('verification', value);
export const publishabilityLabel = value => labelFor('publishability', value);
export const taskLabel = value => labelFor('task', value);
export const severityLabel = value => labelFor('severity', value);
export const sourceTypeLabel = value => labelFor('sourceType', value, '其他资料');
export const activityLabel = value => labelFor('activity', value, '未知活动');
export const connectionLabel = value => labelFor('connection', value);
export const domainLabel = value => labelFor('domain', value, '当前兴趣');
export const platformLabel = value => labelFor('platform', value, '未知平台');
export const capabilityLabel = value => labelFor('capability', value, '本轮对话');
export const revisionModeLabel = value => labelFor('revisionMode', value, '修改');

const REVERIFICATION_REASON_LABELS = {
  missing_current_version: '缺少当前版本，需要重新核对',
  no_supporting_evidence: '还没有支持证据，需要重新核对',
  supporting_evidence_not_human_verified: '支持证据尚未完成人工核验',
  source_verification_missing_or_revoked: '来源核验缺失或已撤销',
  claim_not_human_verified: '主张尚未完成人工核验',
  never_verified_current_version: '当前版本尚未核验',
  verification_stale: '核验时间已久，需要重新查看',
};

const ENGINE_REASON_LABELS = {
  'FEATURE_DEEP_RESEARCH disabled': '深入研究能力暂未启用',
  'engine planning failed': '研究计划暂时无法建立',
};

const REVIEW_ISSUE_LABELS = {
  no_supporting_evidence: '还没有支持证据，不能进入人工核验。',
  missing_supporting_evidence: '引用的部分支持证据已经不存在。',
  support_not_human_verified: '至少一条支持证据尚未完成人工核验。',
  source_not_human_verified: '至少一条支持证据没有指向已人工核验的来源。',
  ai_summary_only_source: '支持证据仍依赖自动摘要，不能作为已核验证据链。',
  no_counter_or_boundary_evidence: '还没有记录相反或边界证据，请确认是否存在条件、例外或争议。',
  missing_counter_evidence: '部分相反或边界证据已经不存在，需要重新核对。',
  missing_limitations: '主张没有写明限制或适用边界。',
  confidence_exceeds_evidence_base: '当前证据数量不足以支持这么高的置信度。',
  absolute_language: '表述可能过于绝对，请确认研究是否支持这样的强度。',
  diagnostic_language: '表述包含个体诊断意味，不能把群体研究直接转为个体诊断。',
  causal_language: '表述包含因果意味，请确认研究设计足以支持因果推断。',
  learning_only_boundary: '当前主张只适合内部学习或暂缓公开。',
};

const RISK_REVIEW_LABELS = {
  language_risk: '这段表达需要根据当前领域规则进一步检查。',
  claim_not_human_verified: '引用的主张尚未完成人工核验。',
  support_not_fully_verified: '引用主张的支持证据尚未全部核验。',
  ai_summary_only_source: '引用主张仍依赖自动摘要来源。',
  claim_not_publishable: '引用主张当前只适合内部学习，暂缓公开。',
  claim_has_no_counter_evidence: '引用主张还没有相反或边界证据。',
  no_human_verified_evidence: '当前领域要求事实表达建立人工核验的证据链。',
  no_counter_evidence: '当前内容还没有记录相反或边界证据。',
};

export function reverificationReasonLabel(value) {
  return labelForMap(REVERIFICATION_REASON_LABELS, value, '需要重新核验');
}

export function engineReasonLabel(value) {
  return labelForMap(ENGINE_REASON_LABELS, value, '研究结果不完整，需要进一步检查');
}

export function reviewIssueLabel(issue) {
  return labelForMap(REVIEW_ISSUE_LABELS, issue?.code, '这项内容需要进一步检查。');
}

export function riskReviewLabel(review) {
  return labelForMap(RISK_REVIEW_LABELS, review?.code, '这项内容需要根据当前领域规则进一步检查。');
}

function labelForMap(map, value, fallback) {
  const raw = String(value ?? '').trim();
  return raw && map[raw] ? map[raw] : fallback;
}

export function statusLabel(value) {
  return taskLabel(value);
}

export function errorCode(error) {
  return String(error?.code || error?.cause?.code || '').toUpperCase();
}

export function toUserMessage(error, context = {}) {
  const code = errorCode(error);
  const status = Number(error?.status || error?.httpStatus || 0);
  const remote = context.remote === true;
  if (code === 'REMOTE_TOKEN_EXPIRED' || code === 'LOGIN_EXPIRED' || status === 401) return '登录状态已过期，请重新连接服务器。';
  if (code === 'IDENTITY_CHANGED' || code === 'SERVER_IDENTITY_CHANGED') return '服务器身份发生变化，请重新验证后再接入。';
  if (code === 'RATE_LIMITED' || status === 429) return '请求有些频繁，请稍后再试。';
  if (code === 'FORBIDDEN' || status === 403) return '当前账号没有执行这项操作的权限。';
  if (status === 404) return '没有找到这项内容，它可能已被移动或归档。';
  if (status === 409) return '当前内容已经发生变化，请刷新后再试。';
  if (status === 422 || code === 'VALIDATION_ERROR') return '有些内容还需要补充或调整，请检查输入。';
  if (status >= 500 || code === 'REMOTE_SERVICE_ERROR') return remote ? '自托管服务器暂时出错，请稍后重试。' : '本地服务暂时出错，请稍后重试。';
  if (code === 'REMOTE_SERVICE_UNAVAILABLE' || code === 'NETWORK_UNAVAILABLE') return remote ? '暂时连接不到你的自托管服务器，请稍后重试。' : '暂时连接不到本地服务，请稍后重试。';
  if (code === 'LOCAL_SERVICE_UNAVAILABLE') return '暂时连接不到本地服务。你的内容仍安全保存在设备上，请稍后重试。';
  if (code === 'INVALID_EXTERNAL_URL') return '链接无效。请使用以 http 或 https 开头的公开链接。';
  if (code === 'UNSUPPORTED_EXTERNAL_URL') return '暂不支持这种链接类型，请使用 http 或 https 链接。';
  if (code === 'DISABLED') return '这项能力目前没有启用，可以在设置中重新打开。';
  return context.fallback || '刚才没有完成，请再试一次。';
}

export const presentationLabels = labels;
