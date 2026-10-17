/**
 * A9's pages (command center + compliance) are loaded lazily from their index.tsx default
 * exports. import.meta.glob keeps the build green while A9's files don't exist yet: the route
 * then shows a "not available yet" placeholder instead of failing the whole app.
 * features/compliance/index.tsx may also export ApprovalsPage / AuditPage / ValidationPage;
 * otherwise its default export serves all three routes (and reads the path itself).
 */
import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from "react";
import { Link } from "react-router-dom";
import { EmptyState, Spinner } from "./ui";

type PageModule = { default?: ComponentType; [name: string]: unknown };

const commandModules = import.meta.glob<PageModule>("../features/command/index.tsx");
const complianceModules = import.meta.glob<PageModule>("../features/compliance/index.tsx");

function lazyFrom(
  modules: Record<string, () => Promise<PageModule>>,
  exportName: string | null,
  label: string,
): LazyExoticComponent<ComponentType> {
  const loader = Object.values(modules)[0];
  return lazy(async () => {
    if (!loader) return { default: () => <NotAvailable label={label} /> };
    const mod = await loader();
    const named = exportName ? (mod[exportName] as ComponentType | undefined) : undefined;
    const Comp = named ?? mod.default;
    return { default: Comp ?? (() => <NotAvailable label={label} />) };
  });
}

function NotAvailable({ label }: { label: string }) {
  return (
    <div className="mx-auto max-w-xl pt-10">
      <EmptyState title={`${label} is not available in this build yet`} action={<Link className="btn-secondary" to="/">Back to import</Link>}>
        This page is built by another module (A9) and loads automatically once it is present.
      </EmptyState>
    </div>
  );
}

const CommandPage = lazyFrom(commandModules, null, "Command center");
const ApprovalsPage = lazyFrom(complianceModules, "ApprovalsPage", "Approvals");
const AuditPage = lazyFrom(complianceModules, "AuditPage", "Audit trail");
const ValidationPage = lazyFrom(complianceModules, "ValidationPage", "Validation package");

function withSuspense(Comp: ComponentType) {
  return function Suspended() {
    return (
      <Suspense fallback={<div className="pt-10"><Spinner label="Loading page" /></div>}>
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
