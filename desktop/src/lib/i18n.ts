/**
 * Tiny message bag with `en` / `zh-CN`. We don't need a full i18n framework
 * for a setup wizard — a typed lookup table is enough.
 */
import { derived, get, writable } from 'svelte/store';

type Lang = 'en' | 'zh-CN';

const messages = {
  en: {
    appName: 'Hyacine',
    tagline: 'Your personal Outlook daily report — powered by Claude.',
    continue: 'Continue',
    back: 'Back',
    skip: 'Skip',
    next: 'Next',
    finish: 'Finish',
    getStarted: 'Get started',
    welcome: 'Welcome',
    theme: 'Appearance',
    themeLight: 'Light',
    themeDark: 'Dark',
    themeAuto: 'System',
    language: 'Language',
    identity: 'Who are you?',
    identityName: 'Name',
    identityRole: 'Role',
    identityBlurb: 'Tell Claude about your work (what matters most, who to watch for)',
    priorities: 'What should always rise to the top?',
    prioritiesHint: 'Add signals that promote a message to the must-do list.',
    delivery: 'Where should the briefing land?',
    deliveryEmail: 'Delivery email',
    deliveryTz: 'Timezone',
    deliveryLang: 'Output language',
    providerTitle: 'Pick your LLM provider',
    providerSubtitle: 'Claude, OpenAI, DeepSeek, local Ollama — or anything OpenAI-compatible.',
    providerKeyLabel: 'API key',
    providerPrivacy:
      'Your key is stored in the OS keychain (Keychain / DPAPI / Secret Service). It never touches disk in plaintext, is never logged, and is never uploaded.',
    providerTest: 'Test connection',
    providerOk: 'Connected',
    providerBad: 'Test failed',
    providerCustom: 'Custom endpoint',
    providerBaseUrl: 'Base URL',
    providerApiFormat: 'API format',
    providerModel: 'Model',
    graphTitle: 'Connect Microsoft Outlook',
    graphStart: 'Open browser to sign in',
    graphCancel: 'Cancel',
    connectivityTitle: 'Running connectivity checks',
    previewTitle: 'First run preview',
    previewRun: 'Run a dry preview',
    doneTitle: "You're all set",
    launch: 'Launch dashboard'
  },
  'zh-CN': {
    appName: 'Hyacine',
    tagline: '你的 Outlook 每日摘要 — 由 Claude 生成',
    continue: '继续',
    back: '上一步',
    skip: '跳过',
    next: '下一步',
    finish: '完成',
    getStarted: '开始设置',
    welcome: '欢迎',
    theme: '外观',
    themeLight: '浅色',
    themeDark: '深色',
    themeAuto: '跟随系统',
    language: '语言',
    identity: '你是谁？',
    identityName: '姓名',
    identityRole: '职位',
    identityBlurb: '告诉 Claude 你的工作（最关心什么，关注哪些人）',
    priorities: '哪些信息应该优先置顶？',
    prioritiesHint: '添加标签 — 命中这些规则的邮件将被推到「今日必做」。',
    delivery: '摘要发到哪里？',
    deliveryEmail: '接收邮箱',
    deliveryTz: '时区',
    deliveryLang: '输出语言',
    providerTitle: '选择你的 LLM 供应商',
    providerSubtitle: 'Claude、OpenAI、DeepSeek、本地 Ollama，或任意 OpenAI 兼容端点。',
    providerKeyLabel: 'API Key',
    providerPrivacy:
      '密钥只保存在本机系统钥匙串（macOS Keychain / Windows DPAPI / Linux Secret Service）。不会写入明文磁盘、不会进日志、不会上传服务器。',
    providerTest: '测试连接',
    providerOk: '连接正常',
    providerBad: '测试失败',
    providerCustom: '自定义端点',
    providerBaseUrl: 'Base URL',
    providerApiFormat: 'API 格式',
    providerModel: '模型',
    graphTitle: '连接 Microsoft Outlook',
    graphStart: '在浏览器中登录',
    graphCancel: '取消',
    connectivityTitle: '正在检查连通性',
    previewTitle: '首次运行预览',
    previewRun: '运行一次预览',
    doneTitle: '全部就绪',
    launch: '进入主界面'
  }
} as const;

type Dict = typeof messages.en;
export type MsgKey = keyof Dict;

export const lang = writable<Lang>('en');
export const t = derived(lang, ($l) => (k: MsgKey) => messages[$l][k] ?? messages.en[k]);

export function tn(k: MsgKey): string {
  return messages[get(lang)][k] ?? messages.en[k];
}
