// Remembers the last opened design so the nav can link the simulator and command center.
const KEY = "tp.lastDesignId";

export function getLastDesignId(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setLastDesignId(id: string): void {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    // storage unavailable: nav falls back to the import page
  }
}
