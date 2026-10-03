/** 破甲目标与可选版本；文案与 fj_tool.py 中的版本表保持一致。 */
import variantInfo from "../../variant.json";

/** 当前构建的变体：free = 全版本；pro = 只提供 V5。 */
export const IS_PRO = variantInfo.variant === "pro";
export const APP_NAME = variantInfo.appName;
/** 界面展示的版本号，由构建变体写入 variant.json。 */
export const APP_VERSION = variantInfo.version || "1.0";

export type Version = {
  /** 展示名 */
  name: string;
  /** 版本说明 */
  desc: string;
  /** 对应根目录下的提示词文件（或安装器识别的版本标识） */
  file: string;
  recommended?: boolean;
  /** 一个版本对应多份提示词时列在这里：点安装会先弹框选具体用哪一份 */
  choices?: VersionChoice[];
};

export type VersionChoice = {
  /** 选择框里的名字 */
  name: string;
  /** 选择框里的一句话说明 */
  desc: string;
  /** 传给安装器的标识（main.cjs 里映射到真实提示词路径） */
  file: string;
};

export type Target = {
  id: string;
  /** 侧栏导航名 */
  nav: string;
  /** 页面小标（英文代号 + 中文） */
  eyebrow: string;
  /** 页面大标题 */
  title: string;
  /** 页面导语 */
  desc: string;
  versions: Version[];
  /** 卸载按钮文案；没有该字段表示不支持卸载 */
  uninstallLabel: string;
  /** 主视觉卡片的图标字 */
  icon: string;
};

const FREE_TARGETS: Target[] = [
  {
    id: "codex",
    icon: "Cx",
    nav: "Codex 破甲",
    eyebrow: "CODEX 顶尖模型",
    title: "顶尖破甲",
    desc:
      "V1 到 V5 只是排序问题，并不是新旧。选中下方任一版本后点击安装，" +
      "提示词写入本机 Codex 配置并注入 AGENTS.md（原有内容自动备份、只追加），重启后输入激活词即可生效。",
    uninstallLabel: "卸载 Codex",
    versions: [
      {
        name: "顶尖破甲 V5",
        desc: "GPT-6 Astra / GPT-5.6 Sol 双提示词 · 安装时选「六」或「5.6」· 不装任何 skills",
        file: "codex-astra-6",
        recommended: true,
        choices: [
          {
            name: "六 · GPT-6 Astra",
            desc: "Astra 事务提交规范 · 适合 GPT-6.0",
            file: "codex-astra-6",
          },
          {
            name: "5.6 · GPT-5.6 Sol",
            desc: "Sol 无限制执行规范 · 适合 GPT-5.6",
            file: "codex-astra-56",
          },
        ],
      },
      {
        name: "顶尖破甲 V4",
        desc: "最新规范 + 63 模块 V4 专属技能库 · 激活词「寒霜」",
        file: "寒霜v4.md",
      },
      {
        name: "顶尖破甲 V3",
        desc: "寒霜工作规范 · 硬拒绝场景覆盖 + 拒绝话术全清单 + 过程进度播报",
        file: "寒霜v3.md",
      },
      {
        name: "顶尖破甲 V2",
        desc: "完整 CTF Lab 2.0 规范 · 身份路由 + 交付标准 + 压缩防护（激活词「海鸥 / 启动」）",
        file: "寒霜v1.2.md",
      },
      {
        name: "顶尖破甲 v1",
        desc: "旧版顶尖提示词 · 完整工程规范 · 项目类型分类 + 两阶段交付（英文版）",
        file: "寒霜-变体B-v3-英文.md",
      },
    ],
  },
  {
    id: "zcode",
    icon: "Zc",
    nav: "ZCode 破甲",
    eyebrow: "ZCODE 破甲",
    title: "ZCode 破甲",
    desc: "提示词 + 系统记忆 + 系统提示词，写入 AGENTS.md 与全局记忆；重启 ZCode 生效。",
    uninstallLabel: "卸载 ZCode",
    versions: [
      {
        name: "ZCode 破甲 V4",
        desc: "最新规范 → AGENTS.md + 全局记忆 + 系统提示词 + V4 技能库",
        file: "寒霜v4.md",
        recommended: true,
      },
      {
        name: "ZCode 破甲 V2",
        desc: "CTF Lab 2.0 完整规范（海鸥版）→ 提示词 + 记忆 + 系统提示词（激活词「海鸥 / 启动」）",
        file: "寒霜v1.2.md",
      },
      {
        name: "ZCode 破甲 V3",
        desc: "寒霜工作规范 v3 → AGENTS.md + 全局记忆 + 系统提示词",
        file: "寒霜v3.md",
      },
    ],
  },
  {
    id: "cursor",
    icon: "Cu",
    nav: "Cursor 破甲",
    eyebrow: "CURSOR 破甲",
    title: "Cursor 破甲",
    desc: "寒霜工作规范注入 Cursor 全局规则（User Rules）；卸载时可还原原规则。",
    uninstallLabel: "卸载 Cursor",
    versions: [
      {
        name: "Cursor 破甲 V4",
        desc: "寒霜 v4 规范注入 Cursor 全局规则（推荐）",
        file: "寒霜v4.md",
        recommended: true,
      },
      { name: "Cursor 破甲 V3", desc: "寒霜 v3 规范注入 Cursor 全局规则", file: "寒霜v3.md" },
    ],
  },
  {
    id: "claude",
    icon: "Cl",
    nav: "Claude 破甲",
    eyebrow: "CLAUDE 破甲",
    title: "Claude 破甲",
    desc: "寒霜工作规范注入 ~/.claude/CLAUDE.md，备份原文件可卸载恢复。",
    uninstallLabel: "卸载 Claude",
    versions: [
      {
        name: "Claude 破甲 V4",
        desc: "寒霜工作规范 v4（CLAUDE.md 版）· 自动安装 V4 专属技能",
        file: "寒霜v4-claude.md",
        recommended: true,
      },
      { name: "Claude 破甲 V3", desc: "寒霜工作规范 v3 · Claude Code 版", file: "寒霜v3.md" },
    ],
  },
  {
    id: "workbuddy",
    icon: "Wb",
    nav: "WorkBuddy 破甲",
    eyebrow: "WORKBUDDY 破甲（国际版）",
    title: "WorkBuddy 破甲（国际版）",
    desc: "适配国际版",
    uninstallLabel: "卸载 WorkBuddy",
    versions: [
      {
        name: "WorkBuddy 国际版 V4",
        desc: "寒霜 v4 → 云记忆 + MEMORY.md + 63 技能库（推荐）",
        file: "寒霜v4.md",
        recommended: true,
      },
      {
        name: "WorkBuddy 国际版 V3",
        desc: "寒霜 v3 → 云记忆 + MEMORY.md + 技能库",
        file: "寒霜v3.md",
      },
      {
        name: "WorkBuddy 国际版 V2",
        desc: "海鸥 CTF Lab 2.0 → 云记忆 + MEMORY.md + 技能库",
        file: "寒霜v1.2.md",
      },
    ],
  },
  {
    // WorkBuddy 国内版：同一个程序的两套发行，数据目录不同
    // （国际版 ~/.workbuddy-ai，国内版 ~/.workbuddy），两者可以并存。
    // 所以拆成两个独立目标，各自安装/卸载，互不干扰 ——
    // 合并成一个目标的话，自动探测会优先国际版，国内版永远轮不到。
    id: "workbuddy-cn",
    icon: "Wb",
    nav: "WorkBuddy 国内版",
    eyebrow: "WORKBUDDY 破甲（国内版）",
    title: "WorkBuddy 破甲（国内版）",
    desc: "适配国内版（数据目录 ~/.workbuddy）",
    uninstallLabel: "卸载 WorkBuddy 国内版",
    versions: [
      {
        name: "WorkBuddy 国内版 V4",
        desc: "寒霜 v4 → 云记忆 + MEMORY.md + 63 技能库（推荐）",
        file: "寒霜v4.md",
        recommended: true,
      },
      {
        name: "WorkBuddy 国内版 V3",
        desc: "寒霜 v3 → 云记忆 + MEMORY.md + 技能库",
        file: "寒霜v3.md",
      },
      {
        name: "WorkBuddy 国内版 V2",
        desc: "海鸥 CTF Lab 2.0 → 云记忆 + MEMORY.md + 技能库",
        file: "寒霜v1.2.md",
      },
    ],
  },
  {
    id: "dsh",
    icon: "Ds",
    nav: "DeepSeek Harness 破甲",
    eyebrow: "DEEPSEEK HARNESS 破甲",
    title: "DeepSeek Harness 破甲",
    desc:
      "提示词写入 ~/.dsh/AGENTS.md —— DSH 全局记忆文件，技能同步到 ~/.dsh/skills。" +
      "原文件已备份，卸载可完整还原。",
    uninstallLabel: "卸载 DeepSeek",
    versions: [
      {
        name: "DeepSeek Harness 破甲 V4",
        desc: "寒霜工作规范 v4（Claude Code 版）· 自动安装 V4 专属技能（63 模块）（推荐）",
        file: "寒霜v4-claude.md",
        recommended: true,
      },
      { name: "DeepSeek Harness 破甲 V3", desc: "寒霜工作规范 v3 · Claude Code 版", file: "寒霜v3.md" },
    ],
  },
  {
    // 豆包：全局记忆不在本地磁盘，存在字节云端、绑定账号。
    // 注入走 CDP 驱动客户端自身的登录会话调云端接口（set_agentsmd 整份覆盖），
    // 所以脚本会自动把豆包重启到调试模式；聊天记录在云端，重启不丢。
    id: "doubao",
    icon: "Db",
    nav: "豆包破甲",
    eyebrow: "豆包（Doubao）",
    title: "豆包破甲",
    desc:
      "提示词写入豆包云端全局记忆（AGENTS.md 式，整份覆盖），走客户端自身登录会话。" +
      "需要豆包以调试模式运行，脚本会自动处理；聊天记录在云端，不会丢。",
    uninstallLabel: "卸载豆包",
    versions: [
      {
        name: "豆包破甲 V4",
        desc: "寒霜工作规范 v4（Claude 版）· 写入云端全局记忆（推荐）",
        file: "寒霜v4-claude.md",
        recommended: true,
      },
      { name: "豆包破甲 V3", desc: "寒霜工作规范 v3 · 写入云端全局记忆", file: "寒霜v3.md" },
    ],
  },
  {
    id: "omp",
    icon: "Om",
    nav: "Oh My Pi 破甲",
    eyebrow: "OH MY PI 破甲",
    title: "Oh My Pi 破甲",
    desc:
      "寒霜工作规范写进 Oh My Pi 的原生规则目录（<agentDir>/rules/寒霜注入.mdc，alwaysApply），" +
      "进系统提示、对所有模型生效。这里只提供全局模式；provider 级（只在 Cursor 模型生效）" +
      "走命令行 -Scope cursor，因为强对齐模型会把消息注入判成越狱而拒答。",
    uninstallLabel: "卸载 Oh My Pi",
    versions: [
      {
        name: "Oh My Pi 破甲 V4",
        desc: "寒霜 v4 规范 → 全局规则（推荐）",
        file: "寒霜v4.md",
        recommended: true,
      },
      { name: "Oh My Pi 破甲 V3", desc: "寒霜 v3 规范 → 全局规则", file: "寒霜v3.md" },
    ],
  },
];

export const TUTORIAL_TITLE = "使用教程";

export const TUTORIAL_TEXT = [
  "V1 到 V5 只是排序问题，并不是新旧",
  "codex 顶尖破甲 V5：点安装会弹框选提示词，「六」给 GPT-6.0、「5.6」给 GPT-5.6；这版只写提示词，不装技能",
  "",
  "执行完了 输入激活词「寒霜」 显示“已成功破甲”就是可以了",
  "",
  "ZCode 注入：点 ZCode 卡片安装，自动写入提示词 + 系统记忆 + 系统提示词，重启 ZCode 生效",
  "",
  "DeepSeek Harness 注入：点卡片安装，写入 ~/.dsh/AGENTS.md + 技能库，重启 DSH 生效",
  "DSH 懒人包版：激活词「寒霜」（同 破甲 / 醒来 / 又拒绝了 / 小寒回来），回「已成功」即生效；",
  "复位发「回到直给」；技能 150 个，和寒霜版的技能库不共存（换版本会自动切换）",
  "",
  "如果遇到不行的情况 重新开对话 重新发就行 有时候会概率拒绝的 正常",
  "一般执行一次之后第一次发是会拒绝 重新开个对话就可以了",
  "上下文太长被压缩后 工具会自动检测并弹提示 你发「寒霜」重新激活就行",
  "",
  "如果一直不行 要么是和谐了 要么是中转站惨水 因为安全对齐不一样 给你惨了傻子模型",
  "",
  "每次重启电脑记得重新执行 重启自动复原的",
  "",
  "永久免费       QQ群819678765",
].join("\n");

export const QQ_LINK =
  "https://qun.qq.com/universal-share/share?ac=1&authKey=AmqBRfY3r1aoAQ9Z6fG4of58siZb3km62aQvbjLXwoUjt3428virhAVyuTMJ9b0w&busi_data=eyJncm91cENvZGUiOiI4MTk2Nzg3NjUiLCJ0b2tlbiI6Ijhhd0QrSFBmQzlOa013U3JaTW8zb1FqNWIvckZyNzBiaTh2NFhDTGNJd2pnWFF6Nng3WDF5MzNGNDVHdlJEMkwiLCJ1aW4iOiI5MTI2MjM1MTkifQ%3D%3D&data=8KZavIbYDW81Xal9lPzM3SielXJhsTUeukLp2rlNqnDuRY85txb1DjaK1TvtIqYUQzCC-sUzcaKpdY6fbir13w&svctype=4&tempid=h5_group_info";

/** 满血中转站：导航栏点击后用系统浏览器打开注册页。 */
export const RELAY_LINK = "https://api.zxcbug.com/register";

/** 不会用点这里：导航栏点击后直接用系统浏览器打开 QQ 群。 */
export const HELP_LINK = "https://qm.qq.com/q/4TA0NydIJ2";

export const DISCLAIMER_TITLE = "免责声明";

export const DISCLAIMER_TEXT = [
  "本提示词、文档、代码及相关资料（下称“本内容”）仅供合法的教育学习、授权安全测试、技术研究与知识分享之用。",
  "",
  "1. 本内容仅面向具备完全民事行为能力的成年人。使用者须确保其获取、使用本内容的行为完全遵守所在国家/地区法律法规及第三方平台协议。",
  "2. 严禁将本内容用于任何违法或侵权活动，包括但不限于：制作外挂、网络入侵与 DDoS 攻击、传播恶意软件、伪造证件、诈骗、洗钱、走私、涉及枪械/爆炸物/毒品及危害人身安全的行为、诱导 AI 绕过安全机制实施违法、以及其他侵犯他人合法权益的行为。",
  "3. 使用者将本内容用于非法用途，属其个人独立行为，与提供方无关；由此产生的一切法律后果、经济责任及第三方索赔，均由使用者自行承担。",
  "4. 提供方不对使用者的任何行为承担任何直接或间接责任，不参与、不协助、不鼓励、不默许任何违法行为。",
  "5. 使用、复制、传播本内容即视为已阅读并同意本声明全部条款；不同意请立即停止使用并删除所有副本。",
  "",
  "提供方保留随时更新本声明的权利，更新后自发布之日起生效。",
].join("\n");

export const ACTIVATION_LINE = "已激活 QQ群819678765";

/** 付费版统一注入的提示词说明。 */
const PRO_VERSION_DESC = "付费版v1 路由版 + 106 技能库 · 激活词「寒霜」";

/** 付费版：六个目标全保留，但每个目标只提供 V5。 */
function toProTarget(t: Target): Target {
  return {
    ...t,
    versions: [
      {
        name: t.title + " 付费版v1",
        desc: PRO_VERSION_DESC,
        file: "寒霜v5.md",
        recommended: true,
      },
    ],
  };
}

export const TARGETS: Target[] = IS_PRO ? FREE_TARGETS.map(toProTarget) : FREE_TARGETS;
