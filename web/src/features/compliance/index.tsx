import { useLocation } from "react-router-dom";
import { ApprovalsPage } from "./ApprovalsPage";
import { AuditPage } from "./AuditPage";
import { ValidationPage } from "./ValidationPage";

export { ApprovalsPage, AuditPage, ValidationPage };

/** Fallback when A8 uses the default export for every compliance route. */
export default function CompliancePages() {
  const { pathname } = useLocation();
  if (pathname.startsWith("/audit")) return <AuditPage />;
  if (pathname.startsWith("/validation")) return <ValidationPage />;
  return <ApprovalsPage />;
}
