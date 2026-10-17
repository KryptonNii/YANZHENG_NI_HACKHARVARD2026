import { DEMO_IDENTITIES, roleName, setIdentity, useIdentity } from "./identity";
import { useTranslation } from "./i18n";

/** Top-right demo identity switcher. Clearly labelled: these are not real accounts. */
export function IdentitySwitcher() {
  const t = useTranslation();
  const me = useIdentity();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="identity-switcher" className="text-right text-[11px] font-semibold uppercase leading-tight tracking-wide text-ink-500">
        {t("Demo", "演示")}
        <br />
        {t("identities", "身份")}
      </label>
      <select
        id="identity-switcher"
        data-testid="identity-switcher"
        value={me.user}
        onChange={(e) => setIdentity(e.target.value)}
        className="rounded-lg border border-ink-300 bg-white py-1.5 pl-2.5 pr-8 text-sm font-semibold text-ink-900 focus:border-accent-600 focus:outline-none focus:ring-2 focus:ring-accent-600/30"
        title={t("Demo identities — the API receives X-User / X-Role headers. Signing still asks for a PIN.", "演示身份：API 接收 X-User / X-Role 请求头，签署时仍需输入 PIN 码。")}
      >
        {DEMO_IDENTITIES.map((i) => (
          <option key={i.user} value={i.user}>
            {i.name} · {roleName(i.role)}
          </option>
        ))}
      </select>
    </div>
  );
}
