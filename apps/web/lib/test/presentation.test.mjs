import assert from 'node:assert/strict';
import test from 'node:test';
import {
  activityLabel,
  domainDisplayName,
  engineLabel,
  engineReasonLabel,
  energyLabel,
  platformLabel,
  questionLabel,
  publishabilityLabel,
  reverificationReasonLabel,
  revisionModeLabel,
  reviewIssueLabel,
  riskReviewLabel,
  sourceTypeLabel,
  statusLabel,
  toUserMessage,
  verificationLabel,
} from '../presentation.js';

test('presentation vocabulary maps known backend values and never leaks unknown enums', () => {
  assert.equal(statusLabel('running'), '进行中');
  assert.equal(energyLabel('deep'), '深入');
  assert.equal(questionLabel('active_topic'), '正在探索');
  assert.equal(verificationLabel('human_verified'), '已人工核验');
  assert.equal(publishabilityLabel('internal_only'), '仅内部学习');
  assert.equal(sourceTypeLabel('paper'), '论文');
  assert.equal(revisionModeLabel('rewrite'), '改写');
  assert.equal(platformLabel('macos'), 'macOS');
  assert.equal(reverificationReasonLabel('verification_stale'), '核验时间已久，需要重新查看');
  assert.equal(reviewIssueLabel({ code: 'diagnostic_language', message: 'Claim raw diagnostic' }), '表述包含个体诊断意味，不能把群体研究直接转为个体诊断。');
  assert.equal(riskReviewLabel({ code: 'claim_not_human_verified', message: 'raw human_verified' }), '引用的主张尚未完成人工核验。');
  assert.equal(activityLabel('brand_new_event'), '未知活动');
  assert.equal(verificationLabel('brand_new_backend_state'), '未知状态');
  assert.equal(revisionModeLabel('brand_new_mode'), '修改');
  assert.equal(engineLabel('native'), '本地执行服务');
  assert.equal(engineLabel('new_internal_engine'), '生成通道');
  assert.equal(domainDisplayName({ domain_pack_id: 'psychology', domain_name: 'internal-pack-name' }), '心理学');
  assert.equal(domainDisplayName({ domain_pack_id: 'unknown', domain_name: 'custom-domain-name' }), '自定义兴趣');
  assert.equal(reverificationReasonLabel('brand_new_reason'), '需要重新核验');
  assert.equal(engineReasonLabel('FEATURE_DEEP_RESEARCH disabled'), '深入研究能力暂未启用');
  assert.equal(engineReasonLabel('brand_new_reason'), '研究结果不完整，需要进一步检查');
  assert.equal(reviewIssueLabel({ code: 'brand_new_issue', message: 'raw internal detail' }), '这项内容需要进一步检查。');
  assert.equal(riskReviewLabel({ code: 'brand_new_risk', message: 'raw internal detail' }), '这项内容需要根据当前领域规则进一步检查。');
});

test('error copy is safe for common HTTP and transport failures', () => {
  assert.equal(toUserMessage({ status: 401 }), '登录状态已过期，请重新连接服务器。');
  assert.equal(toUserMessage({ status: 500 }, { remote: true }), '自托管服务器暂时出错，请稍后重试。');
  assert.equal(toUserMessage({ code: 'INVALID_EXTERNAL_URL' }), '链接无效。请使用以 http 或 https 开头的公开链接。');
  assert.equal(toUserMessage({ message: 'invalid authentication state' }), '刚才没有完成，请再试一次。');
});
