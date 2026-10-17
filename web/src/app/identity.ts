import { useSyncExternalStore } from "react";
import type { Role } from "./contracts";
import { translate } from "./i18n";

/**
 * Demo identities (A7 demo users: alex.author, riley.reviewer, sam.qa).
 * DEMO ONLY: the API trusts X-User / X-Role headers for the hackathon demo; signing still
 * re-authenticates with a PIN on the server. This is not an authentication scheme.
 */
export interface DemoIdentity {
  user: string;
  role: Role;
  name: string;
  roleLabel: string;
}

export const DEMO_IDENTITIES: readonly DemoIdentity[] = [
  { user: "alex.author", role: "author", name: "Alex", roleLabel: "Author" },
  { user: "riley.reviewer", role: "reviewer", name: "Riley", roleLabel: "Reviewer" },
  { user: "sam.qa", role: "qa", name: "Sam", roleLabel: "QA" },
];

const STORAGE_KEY = "tp.identity";
const listeners = new Set<() => void>();

function initial(): DemoIdentity {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    const found = DEMO_IDENTITIES.find((i) => i.user === saved);
    if (found) return found;
  } catch {
    // storage unavailable (private window, tests): fall back to the author
  }
  return DEMO_IDENTITIES[0];
}

let current: DemoIdentity = initial();

export function getIdentity(): DemoIdentity {
  return current;
}

export function setIdentity(user: string): void {
  const next = DEMO_IDENTITIES.find((i) => i.user === user);
  if (!next || next === current) return;
  current = next;
  try {
    localStorage.setItem(STORAGE_KEY, user);
  } catch {
    // ignore
  }
  listeners.forEach((l) => l());
}

export function subscribeIdentity(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Headers sent with every API request (A5/A7 read them as the demo actor). */
export function identityHeaders(): Record<string, string> {
  return { "X-User": current.user, "X-Role": current.role };
}

export function useIdentity(): DemoIdentity {
  return useSyncExternalStore(subscribeIdentity, getIdentity, getIdentity);
}

const ROLE_EN: Record<string, string> = {
  author: "Author", reviewer: "Reviewer", qa: "QA", admin: "Admin", viewer: "Viewer",
  Author: "Author", Reviewer: "Reviewer", QA: "QA", Admin: "Admin", Viewer: "Viewer",
};
const ROLE_ZH: Record<string, string> = {
  author: "作者", reviewer: "审核员", qa: "质量保证", admin: "管理员", viewer: "查看者",
  Author: "作者", Reviewer: "审核员", QA: "质量保证", Admin: "管理员", Viewer: "查看者",
};

/** Role label for the current language. English labels stay Author / Reviewer / QA. */
export function roleName(role: string): string {
  return translate(ROLE_EN[role] ?? role, ROLE_ZH[role] ?? ROLE_ZH[ROLE_EN[role] ?? ""] ?? role);
}

/** "alex.author" → "Alex (Author)"; unknown users are shown as-is. */
export function displayName(user: string): string {
  const found = DEMO_IDENTITIES.find((i) => i.user === user);
  return found ? `${found.name} (${roleName(found.role)})` : user;
}
