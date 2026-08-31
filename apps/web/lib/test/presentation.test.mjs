import assert from 'node:assert/strict';
import test from 'node:test';
import {
  activityLabel,
  publishabilityLabel,
  toUserMessage,
  verificationLabel,
} from '../presentation.js';

test('presentation vocabulary never leaks unknown backend enums', () => {
  assert.equal(verificationLabel('human_verified'), '已人工核验');
  assert.equal(publishabilityLabel('internal_only'), '仅内部学习');
  assert.equal(activityLabel('brand_new_event'), '未知活动');
  assert.equal(verificationLabel('brand_new_backend_state'), '未知状态');
});

test('error copy is safe for common HTTP and transport failures', () => {
  assert.equal(toUserMessage({ status: 401 }), '登录状态已过期，请重新连接服务器。');
  assert.equal(toUserMessage({ status: 500 }, { remote: true }), '自托管服务器暂时出错，请稍后重试。');
  assert.equal(toUserMessage({ code: 'INVALID_EXTERNAL_URL' }), '链接无效。请使用以 http 或 https 开头的公开链接。');
  assert.equal(toUserMessage({ message: 'invalid authentication state' }), '刚才没有完成，请再试一次。');
});
