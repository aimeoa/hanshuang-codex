import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  APP_NAME,
  APP_VERSION,
  TARGETS,
  DISCLAIMER_TEXT,
  DISCLAIMER_TITLE,
  QQ_LINK,
  RELAY_LINK,
  HELP_LINK,
} from "./data/targets";
import { hs, type InstalledMap, type Skill } from "./lib/hs";
import { cx } from "./lib/cx";
import {
  IconBookOpen,
  IconBot,
  IconChat,
  IconCheck,
  IconCircleAlert,
  IconCode,
  IconDatabase,
  IconGlobe,
  IconHelp,
  IconListChecks,
  IconSparkles,
  IconTerminal,
  IconUser,
  IconWrench,
} from "./components/icons";
import brandMark from "./assets/brand.png";
import { InstallPage } from "./pages/InstallPage";
import { SkillsPage } from "./pages/SkillsPage";
import { TutorialPage } from "./pages/TutorialPage";
import { ProfilePage } from "./pages/ProfilePage";

type ViewId = string; // target id | "skills" | "tutorial" | "profile"
export type StatusLevel = "idle" | "busy" | "ok" | "err";

/** 已安装标记 → 提示词文件；启动自动注入时沿用哪一版。 */
const LABEL_TO_FILE: Record<string, string> = {
  // V5 双提示词：已安装记录里带的是「六 / 5.6」，开机自动注入要还原成同一份
  "V5(六)": "codex-astra-6",
  "V5(5.6)": "codex-astra-56",
  V5: "寒霜v5.md",
  V4: "寒霜v4.md",
  V3: "寒霜v3.md",
  V2: "寒霜v1.2.md",
  v1: "寒霜-变体B-v3-英文.md",
};

/** 每个目标一个图标，全部取自 PI-Desktop 的 icons.tsx。 */
const TARGET_ICONS: Record<string, typeof IconSparkles> = {
  codex: IconSparkles,
  zcode: IconTerminal,
  cursor: IconCode,
  claude: IconBot,
  workbuddy: IconGlobe,
  dsh: IconDatabase,
  doubao: IconChat,
  omp: IconWrench,
};

export function App() {
  const [consent, setConsent] = useState(false);
  const [view, setView] = useState<ViewId>("codex");
  const [installed, setInstalled] = useState<InstalledMap>({});
  const [autoInstall, setAutoInstallState] = useState(false);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("就绪");
  const [level, setLevel] = useState<StatusLevel>("idle");
  const [logText, setLogText] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [toastLevel, setToastLevel] = useState<"success" | "error">("success");
  const autoRan = useRef(false);

  // 窗口标题跟随变体（免费版 / 付费版 Pro）
  useEffect(() => {
    document.title = APP_NAME;
  }, []);

  useEffect(() => {
    hs.state().then((s) => {
      setInstalled(s.installed || {});
      setAutoInstallState(!!s.autoInstall);
    });
    hs.listSkills().then(setSkills);
  }, []);

  useEffect(() => {
    const offLog = hs.onLog((p) => setLogText((prev) => (prev + p.text).slice(-20000)));
    const offStatus = hs.onStatus((p) => {
      setBusy(p.state === "running");
      setStatus(p.label);
      setLevel(p.state === "running" ? "busy" : "idle");
    });
    const offNotify = hs.onNotify((p) => setToast(p.text));
    return () => {
      offLog();
      offStatus();
      offNotify();
    };
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 8000);
    return () => clearTimeout(t);
  }, [toast]);

  const reloadSkills = useCallback(() => {
    hs.listSkills().then(setSkills);
  }, []);

  const runInstall = useCallback(async (targetId: string, file: string, label?: string) => {
    const shown = label || file;
    setLogText("");
    setStatus("正在安装 " + shown + " …");
    setLevel("busy");
    setBusy(true);
    const res = await hs.install(targetId, file);
    setInstalled(res.installed || {});
    if (res.ok) {
      setStatus(shown + " 注入成功 · 重启后生效");
      setLevel("ok");
    } else if (res.timedOut) {
      setStatus("安装超时，已强制终止");
      setLevel("err");
    } else {
      setStatus("安装失败（退出码 " + res.code + "）");
      setLevel("err");
    }
    setBusy(false);
    reloadSkills();
  }, [reloadSkills]);

  const runUninstall = useCallback(async (targetId: string) => {
    setLogText("");
    setStatus("正在卸载 …");
    setLevel("busy");
    setBusy(true);
    const res = await hs.uninstall(targetId);
    setInstalled(res.installed || {});
    setStatus(res.ok ? "已卸载 · 技能已一并清除" : "卸载失败（退出码 " + res.code + "）");
    setLevel(res.ok ? "ok" : "err");
    setBusy(false);
    reloadSkills();
  }, [reloadSkills]);

  const runRestart = useCallback(async () => {
    setStatus("正在重启 Codex …");
    setLevel("busy");
    const res = await hs.restartCodex();
    if (res.ok) {
      setStatus("Codex 已重启");
      setLevel("ok");
    } else {
      setStatus("重启失败：" + (res.error || "未知错误"));
      setLevel("err");
    }
  }, []);

  const toggleAuto = useCallback(async () => {
    const next = !autoInstall;
    setAutoInstallState(next);
    await hs.setAutoInstall(next);
  }, [autoInstall]);

  const saveSkills = useCallback(
    async (disabled: string[]) => {
      const res = await hs.saveSkills(disabled);
      if (res.ok) {
        setStatus("Skills 配置已保存 — 重启 Codex 生效");
        setLevel("ok");
        // Skills 页看不到底部状态行，补一个全局提示
        setToastLevel("success");
        setToast("Skills 配置已保存 · 重启 Codex 生效");
        reloadSkills();
      } else {
        setStatus("保存失败：" + (res.error || "无法写入 config.toml"));
        setLevel("err");
        setToastLevel("error");
        setToast("保存失败：" + (res.error || "无法写入 config.toml"));
      }
    },
    [reloadSkills],
  );

  useEffect(() => {
    if (!consent || !autoInstall || autoRan.current) return;
    autoRan.current = true;
    const label = typeof installed.codex === "string" ? installed.codex : "";
    runInstall("codex", LABEL_TO_FILE[label] || "寒霜v4.md");
    // 仅在首次同意后触发一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consent, autoInstall]);

  const current = useMemo(() => TARGETS.find((t) => t.id === view), [view]);
  // hs.openQQ 是通用的 http(s) 外链桥（主进程走 shell.openExternal），中转站链接复用同一通道。
  const openLink = (url: string) => hs.openQQ(url);
  const openQQ = () => openLink(QQ_LINK);
  const openRelay = () => openLink(RELAY_LINK);
  const openHelp = () => openLink(HELP_LINK);

  const navItem = (id: ViewId, label: string, Icon: typeof IconSparkles) => (
    <button
      key={id}
      type="button"
      className={cx("settings-nav-item", view === id && "active")}
      onClick={() => setView(id)}
    >
      <span className="settings-nav-icon">
        <Icon size={16} />
      </span>
      <span className="settings-nav-label">{label}</span>
    </button>
  );

  return (
    <div className="app-shell settings-mode">
      <div className="settings-shell-full">
        <nav className="settings-nav">
          <div className="settings-nav-top">
            <div className="app-brand">
              <img className="app-brand-mark" src={brandMark} alt="" aria-hidden="true" draggable={false} />
              <div className="app-brand-copy">
                <div className="app-brand-name">{APP_NAME}</div>
                <div className="app-brand-meta">{"v" + APP_VERSION}</div>
              </div>
            </div>
          </div>

          <div className="settings-nav-scroll">
            <div className="settings-nav-group">
              <div className="settings-nav-group-label">破甲目标</div>
              {TARGETS.map((t) => navItem(t.id, t.nav, TARGET_ICONS[t.id] || IconSparkles))}
            </div>
            <div className="settings-nav-group">
              <div className="settings-nav-group-label">工具</div>
              {navItem("skills", "Skills 管理", IconListChecks)}
              {navItem("tutorial", "使用教程", IconBookOpen)}
              {/* 与个人中心那张 QQ 卡片同一个链接，点开直接进群 */}
              <button type="button" className="settings-nav-item" onClick={openQQ}>
                <span className="settings-nav-icon">
                  <IconChat size={16} />
                </span>
                <span className="settings-nav-label">加入QQ群</span>
              </button>
              {/* 点击直接用系统浏览器打开中转站注册页 */}
              <button type="button" className="settings-nav-item" onClick={openRelay}>
                <span className="settings-nav-icon">
                  <IconGlobe size={16} />
                </span>
                <span className="settings-nav-label">满血中转站</span>
              </button>
              {/* 不会用点这里：直接跳 QQ 群 */}
              <button type="button" className="settings-nav-item" onClick={openHelp}>
                <span className="settings-nav-icon">
                  <IconHelp size={16} />
                </span>
                <span className="settings-nav-label">不会用点这里</span>
              </button>
            </div>
          </div>

          <div className="app-nav-foot">
            <button
              type="button"
              className={cx("settings-nav-item", view === "profile" && "active")}
              onClick={() => setView("profile")}
            >
              <span className="settings-nav-icon">
                <IconUser size={16} />
              </span>
              <span className="settings-nav-label">个人中心</span>
            </button>
          </div>
        </nav>

        <div className="settings-content">
          <div className="settings-content-inner">
            {current && (
              <InstallPage
                key={current.id}
                target={current}
                installed={installed[current.id]}
                busy={busy}
                status={status}
                level={level}
                logText={logText}
                onInstall={(file, label) => runInstall(current.id, file, label)}
                onUninstall={() => runUninstall(current.id)}
                onRestart={runRestart}
              />
            )}
            {view === "skills" && (
              <SkillsPage skills={skills} onSave={saveSkills} onReload={reloadSkills} />
            )}
            {view === "tutorial" && <TutorialPage />}
            {view === "profile" && (
              <ProfilePage
                version={APP_VERSION}
                status={status}
                level={level}
                autoInstall={autoInstall}
                onToggleAuto={toggleAuto}
                onOpenQQ={openQQ}
                onQuit={() => hs.quit()}
              />
            )}
          </div>
        </div>
      </div>

      {toast && (
        <div
          className={cx("toast", toastLevel === "error" ? "toast-error-solid" : "toast-success-solid")}
          onClick={() => setToast(null)}
        >
          {toastLevel === "error" ? <IconCircleAlert size={16} /> : <IconCheck size={16} />}
          <span>{toast}</span>
        </div>
      )}

      {!consent && (
        <div className="overlay">
          <div className="dialog">
            <h2 className="settings-card-heading">{DISCLAIMER_TITLE}</h2>
            <div className="consent-body">{DISCLAIMER_TEXT}</div>
            <div className="app-inline-actions">
              <button type="button" className="btn btn-primary" onClick={() => setConsent(true)}>
                我同意 并接受所有条约
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => hs.quit()}>
                拒绝并退出
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
