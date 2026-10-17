import { NavLink, Outlet, useLocation } from "react-router-dom";
import { MOCK_API, useHealth } from "./health";
import { IdentitySwitcher } from "./IdentitySwitcher";
import { useTranslation } from "./i18n";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { DEMO_TRIAL_ID, getLastDesignId } from "./lastDesign";
import { Badge, Dot } from "./ui";

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
      <rect width="32" height="32" rx="7" fill="#0f766e" />
      <path d="M8 21l6-6 4 4 7-8" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="25" cy="11" r="2.2" fill="#fff" />
    </svg>
  );
}

function StatusBadges() {
  const t = useTranslation();
  const health = useHealth();
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="status-badges">
      <Badge tone="neutral" title={t("Every number is an estimate with a P10–P90 range and a provenance trail", "每个数值均为估算值，附有 P10–P90 区间和来源记录")}>
        {t("Prototype — estimates with ranges", "原型 · 估算值附有区间")}
      </Badge>
      {MOCK_API && (
        <Badge tone="dark" title={t("VITE_MOCK_API=1: the browser answers API calls with fictional mock data. Not real estimates.", "VITE_MOCK_API=1：浏览器使用虚构数据响应 API 请求，并非真实估算。")}>
          <Dot className="bg-caution-400" /> {t("Mock API — fictional data", "模拟 API · 虚构数据")}
        </Badge>
      )}
      {health.kind === "ok" && health.offline && (
        <Badge tone="caution" title={t("DEMO_OFFLINE=1: external calls are served from cached fixtures", "DEMO_OFFLINE=1：外部请求使用缓存数据响应")}>
          <Dot className="bg-caution-500" /> {t("Offline mode — cached data", "离线模式 · 缓存数据")}
        </Badge>
      )}
      {health.kind === "unreachable" && (
        <Badge tone="worse" title="GET /api/health failed">
          <Dot className="bg-worse-500" /> {t("API unreachable", "无法连接 API")}
        </Badge>
      )}
    </div>
  );
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-2.5 py-1.5 text-sm font-semibold transition-colors ${
    isActive ? "bg-accent-50 text-accent-800" : "text-ink-600 hover:bg-ink-100 hover:text-ink-900"
  }`;

export function Layout() {
  const t = useTranslation();
  useLocation(); // re-render on navigation so the "last design" links stay current
  const last = getLastDesignId();
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        {t("Skip to content", "跳转到正文")}
      </a>
      <header className="sticky top-0 z-40 border-b border-ink-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-6 py-2.5">
          <NavLink to="/" className="flex items-center gap-2.5" aria-label={t("TrialPilot home", "TrialPilot 首页")}>
            <Logo />
            <span className="text-lg font-bold tracking-tight text-ink-900">TrialPilot</span>
          </NavLink>
          <nav aria-label={t("Main", "主导航")} className="flex flex-1 flex-wrap items-center gap-0.5">
            <span className="mr-1 hidden text-[11px] font-bold uppercase tracking-wider text-ink-400 xl:inline">{t("Plan", "规划")}</span>
            <NavLink to="/" end className={navCls}>
              {t("Import", "导入")}
            </NavLink>
            {last && (
              <NavLink to={`/scenario/${encodeURIComponent(last)}`} className={navCls}>
                {t("Simulator", "模拟器")}
              </NavLink>
            )}
            <NavLink to="/compare" className={navCls}>
              {t("Compare", "对比")}
            </NavLink>
            <span className="ml-3 mr-1 hidden text-[11px] font-bold uppercase tracking-wider text-ink-400 xl:inline">{t("Run", "执行")}</span>
            <NavLink to={`/command/${encodeURIComponent(last ?? DEMO_TRIAL_ID)}`} className={navCls}>
              {t("Command center", "指挥中心")}
            </NavLink>
            <span className="ml-3 mr-1 hidden text-[11px] font-bold uppercase tracking-wider text-ink-400 xl:inline">{t("Prove", "验证")}</span>
            <NavLink to="/approvals" className={navCls}>
              {t("Approvals", "审批")}
            </NavLink>
            <NavLink to="/audit" className={navCls}>
              {t("Audit", "审计")}
            </NavLink>
            <NavLink to="/validation" className={navCls}>
              {t("Validation", "验证")}
            </NavLink>
            <NavLink to="/science" className={navCls}>
              {t("Science", "科学依据")}
            </NavLink>
            <NavLink to="/about" className={navCls}>
              {t("About", "关于")}
            </NavLink>
          </nav>
          <IdentitySwitcher />
          <LanguageSwitcher />
        </div>
        <div className="border-t border-ink-100 bg-ink-50/80">
          <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-6 py-1.5">
            <StatusBadges />
            <span className="hidden text-xs text-ink-500 lg:inline">{t("Open source · MIT · every number shows its sources", "开源 · MIT 许可证 · 每个数值均可追溯来源")}</span>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-ink-200 bg-white">
        <div className="mx-auto max-w-[1600px] px-6 py-3 text-xs text-ink-500">
          {t("TrialPilot is a prototype. Figures are estimates with P10–P90 ranges; each links to its formula, parameters and sources. Simulated data is labelled as simulated.", "TrialPilot 为原型系统。数值均为附有 P10–P90 区间的估算值，并链接至相应公式、参数与来源。模拟数据均已明确标注。")}
        </div>
      </footer>
    </div>
  );
}
