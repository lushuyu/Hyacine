/**
 * Typed message bag with `en` / `zh-CN`. Every user-facing string the
 * desktop shell shows goes through here — when you add a new key, add
 * it to both locales.
 *
 * Pattern:
 *   - Top-level "common" keys for verbs/labels reused everywhere
 *     (continue / back / save / retry / …).
 *   - Per-feature key prefix (wizardXxx, appXxx, settingsXxx, …) so
 *     discovery is easy from the Svelte side.
 */
import { derived, get, writable } from 'svelte/store';

type Lang = 'en' | 'zh-CN';

const messages = {
  en: {
    // ── Brand / chrome ───────────────────────────────────────────────
    appName: 'Hyacine',
    tagline: 'Your personal Outlook daily report — powered by {provider}.',

    // ── Common verbs ─────────────────────────────────────────────────
    continue: 'Continue',
    back: 'Back',
    skip: 'Skip',
    next: 'Next',
    finish: 'Finish',
    getStarted: 'Get started',
    save: 'Save',
    saving: 'Saving…',
    saved: 'Saved',
    retry: 'Try again',
    rerun: 'Re-run',
    rotate: 'Rotate',
    signOut: 'Sign out',
    close: 'Close',
    copy: 'Copy',
    loading: 'Loading…',
    running: 'Running…',
    testing: 'Testing…',

    // ── Sidecar ──────────────────────────────────────────────────────
    sidecarUnreachableTitle: 'Sidecar unreachable — showing the bundled provider list only.',
    sidecarUnreachableBody:
      'Connectivity testing and custom endpoints need the Python sidecar to respond. You can still pick a preset; testing will start working once the sidecar is reachable.',

    // ── Welcome step ─────────────────────────────────────────────────
    welcome: 'Welcome',
    theme: 'Appearance',
    themeLight: 'Light',
    themeDark: 'Dark',
    themeAuto: 'System',
    language: 'Language',

    // ── Identity step ────────────────────────────────────────────────
    identity: 'Who are you?',
    identityHint: '{provider} uses this to tone the briefing. It stays on your machine.',
    identityName: 'Name',
    identityRole: 'Role',
    identityBlurb: 'Tell {provider} about your work (what matters most, who to watch for)',
    identityPreview: 'Preview',
    identityPreviewName: 'Your name',
    identityPreviewRole: 'Your role',
    identityPreviewBlurb: 'A short description {provider} can use to tone the briefing.',

    // ── Priorities step ──────────────────────────────────────────────
    priorities: 'What should always rise to the top?',
    prioritiesHint: 'Add signals that promote a message to the must-do list.',
    prioritiesEmpty: 'Pick a few suggestions below, or type your own.',
    prioritiesAddPlaceholder: 'Add a custom signal — press Enter',
    prioritiesSuggested: 'Suggested',

    // ── Delivery step ────────────────────────────────────────────────
    delivery: 'Where should the briefing land?',
    deliveryHint:
      'Hyacine sends the summary to this address every morning, via your own Outlook account.',
    deliveryEmail: 'Delivery email',
    deliveryEmailPlaceholder: 'alice@example.com',
    deliveryEmailInvalid: "Looks like that isn't a valid email.",
    deliveryTz: 'Timezone',
    deliveryTzPlaceholder: 'Type a city or UTC offset…',
    deliveryTzInvalid: 'Unknown timezone.',
    deliveryLang: 'Output language',
    deliveryPreviewTo: 'To',
    deliveryPreviewFrom: 'From',
    deliveryPreviewFromVal: 'Hyacine <via your Outlook>',
    deliveryPreviewSubject: 'Subject',
    deliveryPreviewSubjectVal: 'Your briefing —',
    deliveryPreviewLanguage: 'Language',

    // ── Provider step ────────────────────────────────────────────────
    providerTitle: 'Pick your LLM provider',
    providerSubtitle:
      'Anything that speaks the Claude or OpenAI chat protocol works — pick a preset below, or point Hyacine at your own endpoint.',
    providerKeyLabel: 'API key',
    providerPrivacyHeader: 'Privacy',
    providerPrivacy:
      'Your key is stored in the OS keychain (Keychain / DPAPI / Secret Service). It never touches disk in plaintext, is never logged, and is never uploaded.',
    providerTest: 'Test connection',
    providerOk: 'Connected',
    providerBad: 'Test failed',
    providerCustom: 'Custom endpoint',
    providerCustomSubtitle: 'Point at any Claude-compatible or OpenAI-compatible endpoint.',
    providerBaseUrl: 'Base URL',
    providerApiFormat: 'Protocol',
    providerModel: 'Model',
    providerModelHint: "Pick from the provider's catalogue, or type a model ID.",
    providerModelOther: 'Other (type a model ID)…',
    providerLoadingCatalogue: 'Loading provider catalogue…',
    providerKeyStored: 'Key stored',
    providerKeyStoredNote: 'Slug:',
    providerReplace: 'Replace',
    providerKeyLooksGood: 'Looks good —',
    providerCliHeader: 'Uses the',
    providerCliBody:
      "Two ways to authenticate. (a) If you've already run `claude login` on this machine, leave the field below empty — Hyacine calls the `claude` CLI and it reads your stored credentials automatically. (b) Otherwise run the command below to generate a long-lived token, then paste it into the field.",
    providerCliSetupCmd: 'claude setup-token',
    providerCliPasteOptional: 'Long-lived token (optional)',
    providerCliPasteHint:
      "Leave empty if `claude login` is already done. Otherwise paste the `sk-ant-oat…` token printed by `claude setup-token`.",
    providerDocs: 'Docs',
    providerSectionActiveTitle: 'Connection details',
    providerCategoryOfficial: 'First-party',
    providerCategoryRelay: 'Claude-compatible relays',
    providerCategoryCnOfficial: 'Mainland-China first-party',
    providerCategoryAggregator: 'Multi-model aggregators',
    providerCategoryLocal: 'Run on this machine',
    providerCategoryCustom: 'Custom',
    providerFmtAnthropicCli: 'Claude CLI',
    providerFmtAnthropicHttp: 'Claude protocol',
    providerFmtOpenaiChat: 'OpenAI protocol',
    providerKeyClearedToast: 'Stored key cleared.',
    providerReachableToast: 'Provider reachable',
    providerAnthropicHelp:
      'Claude protocol: enter host + base path, Hyacine appends /v1/messages.',
    providerOpenaiHelp:
      'OpenAI protocol: include the /v1 segment, Hyacine appends /chat/completions.',
    providerCustomBaseUrlAnthropicPH: 'https://api.example.com  (no /v1 suffix)',
    providerCustomBaseUrlOpenaiPH: 'https://api.example.com/v1  (include /v1)',

    // ── Graph step ───────────────────────────────────────────────────
    graphTitle: 'Connect Microsoft Outlook',
    graphSubtitle:
      'Hyacine uses Microsoft Graph device-code sign-in — no password leaves your machine.',
    graphEnterCode: 'Enter this code on the Microsoft sign-in page:',
    graphStart: 'Open browser to sign in',
    graphCancel: 'Cancel',
    graphSignedIn: 'Signed in',
    graphCancelled: 'Cancelled',
    graphFailed: 'Sign-in failed',

    // ── Connectivity step ────────────────────────────────────────────
    connectivityTitle: 'Running connectivity checks',
    connectivitySubtitle: 'Four checks in parallel — they should finish in a few seconds.',
    connectivityDns: 'DNS + outbound TCP',
    connectivityClaude: '{provider} API',
    connectivityGraph: 'Microsoft Graph',
    connectivitySendmail: 'SendMail (test to self)',
    connectivityIncludeSendmail: 'Also send a one-time test email to myself',
    connectivityRerun: 'Re-run checks',
    connectivityStatusRunning: 'Running…',
    connectivityStatusOk: 'OK',
    connectivityStatusFail: 'Failed',
    connectivityStatusSkipped: 'Skipped',
    connectivityStatusNotRunning: 'Not running (optional)',

    // ── Preview step ─────────────────────────────────────────────────
    previewTitle: 'First run preview',
    previewSubtitle:
      "We'll run the full pipeline once without sending an email, so you can see what {provider} produces.",
    previewRun: 'Run again',
    previewHeader: 'Rendered preview',
    previewSubject: 'Subject',
    previewStageFetch: 'Fetch inbox & calendar',
    previewStageClassify: 'Classify messages',
    previewStageLlm: 'Invoke {provider}',
    previewStageRender: 'Render HTML',
    previewStageDeliver: 'Deliver (dry run)',

    // ── Done step ────────────────────────────────────────────────────
    doneTitle: "You're all set",
    doneSubtitle: 'Hyacine will send you a briefing every weekday morning.',
    doneRunTime: 'Daily run time',
    doneRunTimeHint: 'Local time',
    doneLaunchAtLogin: 'Launch at login',
    doneLaunchAtLoginHint: 'Recommended so scheduling works',
    doneTray: 'Show in system tray',
    doneTrayHint: 'Quick access to run now & logs',
    launch: 'Launch dashboard',

    // ── App shell + main tabs ────────────────────────────────────────
    navDashboard: 'Dashboard',
    navPromptLab: 'Prompt Lab',
    navRules: 'Rules',
    navSettings: 'Settings',
    runNow: 'Run now',
    runningNow: 'Running…',
    lastRunOk: 'Last run succeeded',
    lastRunFail: 'Last run failed',
    lastRunWarn: 'Warnings',
    lastRunNone: 'No runs yet',

    // ── Dashboard ────────────────────────────────────────────────────
    dashboardTitle: 'Dashboard',
    dashboardSubtitle: 'Your last 14 runs at a glance.',
    dashboardActivityTitle: 'Activity',
    dashboardActivityLegend: 'Older ← → Newer',
    dashboardLoadingHistory: 'Loading history…',
    dashboardRunDetails: 'Run details',
    dashboardNoRuns: 'No runs yet — hit "Run now" in the sidebar to kick off the first one.',

    // ── Prompt Lab ───────────────────────────────────────────────────
    promptTitle: 'Prompt Lab',
    promptSubtitle: 'This is the system prompt {provider} sees on every run.',
    promptDryRun: 'Dry-run',
    promptSaved: 'Prompt saved',
    promptDryRunSucceeded: 'Dry run succeeded in',

    // ── Rules ────────────────────────────────────────────────────────
    rulesTitle: 'Rules',
    rulesSubtitle: 'YAML classifier rules — promote/demote messages before they reach {provider}.',
    rulesSaved: 'Rules saved',

    // ── Settings ─────────────────────────────────────────────────────
    settingsTitle: 'Settings',
    settingsSubtitle: 'Edit your configuration any time.',
    settingsSectionAppearance: 'Appearance',
    settingsSectionDelivery: 'Delivery',
    settingsSectionCredentials: 'Credentials',
    settingsSectionAdvanced: 'Advanced',
    settingsRecipientEmail: 'Recipient email',
    settingsTimezone: 'Timezone',
    settingsRunTime: 'Run time',
    settingsLanguage: 'Language',
    settingsClaudeModel: '{provider} model',
    settingsLlmProvider: 'LLM provider',
    settingsKeyStoredFor: 'Key stored for',
    settingsKeyNotStored: 'No key stored for this provider',
    settingsNoProvider: 'No provider selected yet',
    settingsConfigure: 'Configure',
    settingsRotateSwitch: 'Rotate / switch',
    settingsMicrosoftAccount: 'Microsoft account',
    settingsMicrosoftNotSigned: 'Not signed in',
    settingsRerunWizardTitle: 'Re-run setup wizard',
    settingsRerunWizardBody:
      'Walks through every step again without deleting stored data.',
    settingsSaved: 'Settings saved',
    settingsGraphSignOutToast: 'Rerun the wizard to re-authenticate Microsoft Graph.'
  },
  'zh-CN': {
    appName: 'Hyacine',
    tagline: '你的 Outlook 每日摘要 —— 由 {provider} 生成',

    continue: '继续',
    back: '上一步',
    skip: '跳过',
    next: '下一步',
    finish: '完成',
    getStarted: '开始设置',
    save: '保存',
    saving: '保存中…',
    saved: '已保存',
    retry: '重试',
    rerun: '重新运行',
    rotate: '更换',
    signOut: '退出登录',
    close: '关闭',
    copy: '复制',
    loading: '加载中…',
    running: '运行中…',
    testing: '测试中…',

    sidecarUnreachableTitle: 'Sidecar 未启动 —— 仅显示内置的供应商列表',
    sidecarUnreachableBody:
      '连通性测试和自定义端点需要 Python sidecar 运行。你仍然可以选择预设；等 sidecar 可达后再做连接测试。',

    welcome: '欢迎',
    theme: '外观',
    themeLight: '浅色',
    themeDark: '深色',
    themeAuto: '跟随系统',
    language: '语言',

    identity: '你是谁？',
    identityHint: '{provider} 会用这些信息调整摘要的语气。仅保存在本机。',
    identityName: '姓名',
    identityRole: '职位',
    identityBlurb: '告诉 {provider} 你的工作（最关心什么、关注哪些人）',
    identityPreview: '预览',
    identityPreviewName: '你的姓名',
    identityPreviewRole: '你的职位',
    identityPreviewBlurb: '一段简短描述，{provider} 会用它来调整摘要语气。',

    priorities: '哪些信息应该优先置顶？',
    prioritiesHint: '添加标签 —— 命中这些规则的邮件将被推到「今日必做」。',
    prioritiesEmpty: '从下面选几个建议，或者自己输入。',
    prioritiesAddPlaceholder: '添加自定义标签 —— 按回车确认',
    prioritiesSuggested: '建议',

    delivery: '摘要发到哪里？',
    deliveryHint: 'Hyacine 每天早上会通过你自己的 Outlook 账户把摘要发送到这个地址。',
    deliveryEmail: '接收邮箱',
    deliveryEmailPlaceholder: 'alice@example.com',
    deliveryEmailInvalid: '这看起来不是合法的邮箱地址。',
    deliveryTz: '时区',
    deliveryTzPlaceholder: '输入城市名或 UTC 偏移…',
    deliveryTzInvalid: '未知时区。',
    deliveryLang: '输出语言',
    deliveryPreviewTo: '收件人',
    deliveryPreviewFrom: '发件人',
    deliveryPreviewFromVal: 'Hyacine（通过你的 Outlook）',
    deliveryPreviewSubject: '主题',
    deliveryPreviewSubjectVal: '你的每日摘要 —',
    deliveryPreviewLanguage: '语言',

    providerTitle: '选择你的 LLM 供应商',
    providerSubtitle:
      '只要说 Claude 或 OpenAI 聊天接口协议的服务都可以 —— 从下面选一个预设，或把 Hyacine 指向你自己的端点。',
    providerKeyLabel: 'API Key',
    providerPrivacyHeader: '隐私说明',
    providerPrivacy:
      '密钥只保存在本机系统钥匙串（macOS Keychain / Windows DPAPI / Linux Secret Service）。不会写入明文磁盘、不会进日志、不会上传服务器。',
    providerTest: '测试连接',
    providerOk: '连接正常',
    providerBad: '测试失败',
    providerCustom: '自定义端点',
    providerCustomSubtitle: '接入任意 Claude 协议或 OpenAI 协议的端点。',
    providerBaseUrl: 'Base URL',
    providerApiFormat: '协议',
    providerModel: '模型',
    providerModelHint: '从供应商给出的模型里选，或手动填入模型 ID。',
    providerModelOther: '其他（手输模型 ID）…',
    providerLoadingCatalogue: '正在加载供应商列表…',
    providerKeyStored: '密钥已保存',
    providerKeyStoredNote: '存储位置：',
    providerReplace: '更换',
    providerKeyLooksGood: '格式正确 —',
    providerCliHeader: '使用',
    providerCliBody:
      '两种登录方式。(a) 如果你已经在本机跑过 `claude login`，下面的输入框留空即可 —— Hyacine 调用 `claude` CLI 时它会自动读取本地凭证。(b) 否则运行下面的命令生成一个长期 token，粘贴到下方的输入框。',
    providerCliSetupCmd: 'claude setup-token',
    providerCliPasteOptional: '长期 token（可选）',
    providerCliPasteHint:
      '已经 `claude login` 过就留空。否则把 `claude setup-token` 打印出来的 `sk-ant-oat…` 粘贴进来。',
    providerDocs: '文档',
    providerSectionActiveTitle: '连接配置',
    providerCategoryOfficial: '官方直连',
    providerCategoryRelay: 'Claude 协议中转',
    providerCategoryCnOfficial: '中国大陆官方',
    providerCategoryAggregator: '多模型聚合',
    providerCategoryLocal: '在本机运行',
    providerCategoryCustom: '自定义',
    providerFmtAnthropicCli: 'Claude CLI',
    providerFmtAnthropicHttp: 'Claude 协议',
    providerFmtOpenaiChat: 'OpenAI 协议',
    providerKeyClearedToast: '已清除保存的密钥。',
    providerReachableToast: '连接正常',
    providerAnthropicHelp: 'Claude 协议：填入主机和基础路径，Hyacine 会自动追加 /v1/messages。',
    providerOpenaiHelp: 'OpenAI 协议：包含 /v1 段，Hyacine 会自动追加 /chat/completions。',
    providerCustomBaseUrlAnthropicPH: 'https://api.example.com  （不要带 /v1）',
    providerCustomBaseUrlOpenaiPH: 'https://api.example.com/v1  （包含 /v1）',

    graphTitle: '连接 Microsoft Outlook',
    graphSubtitle: 'Hyacine 使用微软设备码登录 —— 密码不会离开你的机器。',
    graphEnterCode: '在 Microsoft 登录页输入以下验证码：',
    graphStart: '在浏览器中登录',
    graphCancel: '取消',
    graphSignedIn: '已登录',
    graphCancelled: '已取消',
    graphFailed: '登录失败',

    connectivityTitle: '正在检查连通性',
    connectivitySubtitle: '四项并行检查，几秒内完成。',
    connectivityDns: 'DNS + 出站 TCP',
    connectivityClaude: '{provider} API',
    connectivityGraph: 'Microsoft Graph',
    connectivitySendmail: 'SendMail（给自己发测试邮件）',
    connectivityIncludeSendmail: '同时给自己发一封一次性测试邮件',
    connectivityRerun: '重新检查',
    connectivityStatusRunning: '检查中…',
    connectivityStatusOk: '成功',
    connectivityStatusFail: '失败',
    connectivityStatusSkipped: '跳过',
    connectivityStatusNotRunning: '未运行（可选项）',

    previewTitle: '首次运行预览',
    previewSubtitle: '完整跑一遍流程但不实际发送邮件，让你看到 {provider} 的产出。',
    previewRun: '再运行一次',
    previewHeader: '渲染预览',
    previewSubject: '主题',
    previewStageFetch: '拉取邮件和日程',
    previewStageClassify: '邮件分类',
    previewStageLlm: '调用 {provider}',
    previewStageRender: '渲染 HTML',
    previewStageDeliver: '投递（dry run）',

    doneTitle: '全部就绪',
    doneSubtitle: 'Hyacine 会在每个工作日早上给你发送摘要。',
    doneRunTime: '每日运行时间',
    doneRunTimeHint: '本地时间',
    doneLaunchAtLogin: '开机自启动',
    doneLaunchAtLoginHint: '推荐开启以确保调度正常',
    doneTray: '显示在系统托盘',
    doneTrayHint: '可以快速运行和查看日志',
    launch: '进入主界面',

    navDashboard: '仪表盘',
    navPromptLab: 'Prompt Lab',
    navRules: '规则',
    navSettings: '设置',
    runNow: '立即运行',
    runningNow: '运行中…',
    lastRunOk: '上次运行成功',
    lastRunFail: '上次运行失败',
    lastRunWarn: '有警告',
    lastRunNone: '尚未运行过',

    dashboardTitle: '仪表盘',
    dashboardSubtitle: '最近 14 次运行一览。',
    dashboardActivityTitle: '活动',
    dashboardActivityLegend: '旧 ← → 新',
    dashboardLoadingHistory: '加载历史中…',
    dashboardRunDetails: '运行详情',
    dashboardNoRuns: '还没有运行记录 —— 点侧边栏的「立即运行」来跑第一次。',

    promptTitle: 'Prompt 实验室',
    promptSubtitle: '这是 {provider} 每次运行都会看到的系统 prompt。',
    promptDryRun: '预览运行',
    promptSaved: 'Prompt 已保存',
    promptDryRunSucceeded: '预览运行成功，耗时',

    rulesTitle: '规则',
    rulesSubtitle: 'YAML 分类规则 —— 在邮件进入 {provider} 前做优先级调整。',
    rulesSaved: '规则已保存',

    settingsTitle: '设置',
    settingsSubtitle: '随时调整你的配置。',
    settingsSectionAppearance: '外观',
    settingsSectionDelivery: '投递',
    settingsSectionCredentials: '凭证',
    settingsSectionAdvanced: '高级',
    settingsRecipientEmail: '接收邮箱',
    settingsTimezone: '时区',
    settingsRunTime: '运行时间',
    settingsLanguage: '语言',
    settingsClaudeModel: '{provider} 模型',
    settingsLlmProvider: 'LLM 供应商',
    settingsKeyStoredFor: '已为此 slug 保存密钥：',
    settingsKeyNotStored: '此供应商暂无保存密钥',
    settingsNoProvider: '尚未选择供应商',
    settingsConfigure: '开始配置',
    settingsRotateSwitch: '更换 / 切换',
    settingsMicrosoftAccount: 'Microsoft 账户',
    settingsMicrosoftNotSigned: '未登录',
    settingsRerunWizardTitle: '重新运行设置向导',
    settingsRerunWizardBody: '重新走一遍每一步，不会删除已保存的数据。',
    settingsSaved: '设置已保存',
    settingsGraphSignOutToast: '请重新运行向导以再次认证 Microsoft Graph。'
  }
} as const;

type Dict = typeof messages.en;
export type MsgKey = keyof Dict;

export const lang = writable<Lang>('en');

// Display name of the LLM the pipeline is actually configured to use.
// Populated by the root layout from `providers.current`; message strings
// reference it via the `{provider}` placeholder so the UI reads
// "Invoke DeepSeek" / "调用 Groq" / etc. instead of being hard-coded to
// "Claude". Default keeps something sensible before the sidecar responds.
export const providerName = writable<string>('LLM');

function interpolate(raw: string, vars: Record<string, string | number>): string {
  return raw.replace(/\{(\w+)\}/g, (_m, key) => {
    const v = vars[key];
    return v === undefined ? `{${key}}` : String(v);
  });
}

export const t = derived(
  [lang, providerName],
  ([$l, $p]) =>
    (k: MsgKey, vars?: Record<string, string | number>) => {
      const raw = messages[$l][k] ?? messages.en[k];
      return interpolate(raw, { provider: $p, ...(vars ?? {}) });
    }
);

export function tn(k: MsgKey, vars?: Record<string, string | number>): string {
  const raw = messages[get(lang)][k] ?? messages.en[k];
  return interpolate(raw, { provider: get(providerName), ...(vars ?? {}) });
}
