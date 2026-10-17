import { useSyncExternalStore } from "react";

export type Language = "en" | "zh";
const STORAGE_KEY = "tp.language";
const listeners = new Set<() => void>();

function savedLanguage(): Language {
  try {
    return localStorage.getItem(STORAGE_KEY) === "zh" ? "zh" : "en";
  } catch {
    return "en";
  }
}

let language = savedLanguage();

export function getLanguage(): Language {
  return language;
}

export function setLanguage(next: Language): void {
  language = next;
  if (typeof document !== "undefined") document.documentElement.lang = next === "zh" ? "zh-CN" : "en";
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Language switching still works when browser storage is unavailable.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

const english = (en: string, _zh: string): string => en;
const chinese = (_en: string, zh: string): string => zh;

/** Translate display text without changing the underlying data or component state. */
export function useTranslation(): typeof english {
  const current = useLanguage();
  return current === "zh" ? chinese : english;
}

/** For display helpers called during a subscribed component's render. */
export function translate(en: string, zh: string): string {
  return language === "zh" ? zh : en;
}

export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage, () => "en" as const);
}
