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
