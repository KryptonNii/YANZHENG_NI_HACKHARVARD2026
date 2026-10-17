// Remembers the last opened design so the nav can link the simulator and command center.
const KEY = "tp.lastDesignId";

/** The 40-site demo trial (api ops/fixtures.py DEMO_TRIAL_ID); the command center opens it when no design was opened yet. */
export const DEMO_TRIAL_ID = "demo-40";

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
