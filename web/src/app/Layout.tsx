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
  if (!MOCK_API && !(health.kind === "ok" && health.offline) && health.kind !== "unreachable") return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="status-badges">
      {MOCK_API && (
        <Badge tone="dark" title={t("Fictional sample data", "虚构示例数据")}>
          <Dot className="bg-caution-400" /> {t("Sample data", "示例数据")}
        </Badge>
      )}
      {health.kind === "ok" && health.offline && (
        <Badge tone="caution" title={t("Using saved data", "使用已保存数据")}>
          <Dot className="bg-caution-500" /> {t("Offline", "离线")}
        </Badge>
      )}
      {health.kind === "unreachable" && (
        <Badge tone="worse">
          <Dot className="bg-worse-500" /> {t("Connection unavailable", "连接异常")}
        </Badge>
      )}
    </div>
  );
}

const navCls = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm font-semibold transition-colors ${
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
      {/* Below lg the header wraps: logo + controls on top, the nav on its own row that scrolls sideways;
          below md it is not sticky so it does not cover a phone screen. lg and up is the original single row. */}
      <header className="z-40 border-b border-ink-200 bg-white/95 backdrop-blur md:sticky md:top-0">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2 px-6 py-2.5 lg:flex-nowrap lg:gap-6">
          <NavLink to="/" className="mr-auto flex items-center gap-2.5 lg:mr-0" aria-label={t("TrialPilot home", "TrialPilot 首页")}>
            <Logo />
            <span className="text-lg font-bold tracking-tight text-ink-900">TrialPilot</span>
          </NavLink>
          <nav
            aria-label={t("Main", "主导航")}
            className="order-last flex basis-full items-center gap-0.5 overflow-x-auto py-1 [scrollbar-width:thin] lg:order-none lg:flex-1 lg:flex-wrap lg:overflow-visible lg:py-0"
          >
            <NavLink to="/" end className={navCls}>
              {t("Trials", "试验管理")}
            </NavLink>
            {last && (
              <NavLink to={`/scenario/${encodeURIComponent(last)}`} className={navCls}>
                {t("Analysis", "方案分析")}
              </NavLink>
            )}
            <NavLink to="/compare" className={navCls}>
              {t("Compare", "对比")}
            </NavLink>
            <NavLink to={`/command/${encodeURIComponent(last ?? DEMO_TRIAL_ID)}`} className={navCls}>
              {t("Operations", "运营监控")}
            </NavLink>
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
              {t("Models", "模型验证")}
            </NavLink>
            <NavLink to="/about" className={navCls}>
              {t("Methods", "方法与参数")}
            </NavLink>
          </nav>
          {/* on phones the role selector drops below the language button and badges */}
          <div className="max-sm:order-1">
            <IdentitySwitcher />
          </div>
          <LanguageSwitcher />
          <StatusBadges />
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
