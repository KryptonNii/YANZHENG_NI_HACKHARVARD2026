import { useEffect } from "react";
import { setLanguage, useLanguage } from "./i18n";

export function LanguageSwitcher() {
  const current = useLanguage();
  useEffect(() => {
    document.documentElement.lang = current === "zh" ? "zh-CN" : "en";
  }, [current]);

  return (
    <button
      type="button"
      className="btn-secondary shrink-0 whitespace-nowrap"
      onClick={() => setLanguage(current === "en" ? "zh" : "en")}
      aria-label={current === "en" ? "切换到中文" : "Switch to English"}
      lang={current === "en" ? "zh-CN" : "en"}
    >
      {current === "en" ? "中文" : "English"}
    </button>
  );
}
