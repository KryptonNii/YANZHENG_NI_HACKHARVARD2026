import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { AboutPage } from "../features/scenario/AboutPage";
import { ComparePage } from "../features/scenario/ComparePage";
import { ImportPage } from "../features/scenario/ImportPage";
import { ScenarioPage } from "../features/scenario/ScenarioPage";
import { SciencePage } from "../features/scenario/SciencePage";
import { ExternalPages } from "./externalPages";
import { Layout } from "./Layout";
import { useTranslation } from "./i18n";
import { ToastProvider } from "./toast";
import { EmptyState } from "./ui";

function NotFound() {
  const t = useTranslation();
  return (
    <div className="mx-auto max-w-xl pt-10">
      <EmptyState title={t("Page not found", "页面未找到")} action={<Link className="btn-secondary" to="/">{t("Go to import", "前往导入页面")}</Link>}>
        {t("The address doesn't match any TrialPilot page.", "该地址未匹配到任何 TrialPilot 页面。")}
      </EmptyState>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<ImportPage />} />
        <Route path="scenario/:designId" element={<ScenarioPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="command/:trialId" element={<ExternalPages.Command />} />
        <Route path="approvals" element={<ExternalPages.Approvals />} />
        <Route path="audit" element={<ExternalPages.Audit />} />
        <Route path="validation" element={<ExternalPages.Validation />} />
        <Route path="science" element={<SciencePage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </ToastProvider>
  );
}
