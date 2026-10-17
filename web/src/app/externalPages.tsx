/**
 * A9's pages (command center + compliance) are loaded lazily, so their code is split from the
 * plan pages: the command center is features/command's default export, the compliance pages are
 * features/compliance's named exports.
 */
import { lazy, Suspense, type ComponentType } from "react";
import { Spinner } from "./ui";
import { useTranslation } from "./i18n";

const CommandPage = lazy(() => import("../features/command"));
const ApprovalsPage = lazy(() => import("../features/compliance").then((m) => ({ default: m.ApprovalsPage })));
const AuditPage = lazy(() => import("../features/compliance").then((m) => ({ default: m.AuditPage })));
const ValidationPage = lazy(() => import("../features/compliance").then((m) => ({ default: m.ValidationPage })));

function withSuspense(Comp: ComponentType) {
  return function Suspended() {
    const t = useTranslation();
    return (
      <Suspense fallback={<div className="pt-10"><Spinner label={t("Loading page", "正在加载页面")} /></div>}>
        <Comp />
      </Suspense>
    );
  };
}

export const ExternalPages = {
  Command: withSuspense(CommandPage),
  Approvals: withSuspense(ApprovalsPage),
  Audit: withSuspense(AuditPage),
  Validation: withSuspense(ValidationPage),
};
