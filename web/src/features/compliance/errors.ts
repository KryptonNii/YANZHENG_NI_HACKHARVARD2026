import { translate as t } from "@/app/i18n";
import { ApiError } from "@/app/api/client";

/** Plain-English copy for the signing dialog. Known codes use a fixed sentence so the UI does not depend on wording drift. */
export function signErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return err instanceof Error ? err.message : String(err);
  switch (err.code) {
    case "self_approval_forbidden":
      return t("Authors can't approve their own work.", "作者不能批准自己的工作。");
    case "out_of_order":
      return t(err.message || "Signatures must follow the required order.", "必须按要求的顺序签署。");
    case "account_locked":
      return t(err.message || "Signing is locked after too many wrong PINs.", "PIN 码错误次数过多，签署已锁定。");
    case "invalid_credential":
      return t("Wrong PIN — the signature was not recorded.", "PIN 码错误 — 签名未记录。");
    case "role_not_permitted":
      return t(err.message || "This role cannot sign that meaning.", "此角色无权签署该含义。");
    case "record_changed":
      return t(err.message || "The record changed after it was submitted.", "记录在提交后已更改。");
    default:
      return err.message;
  }
}
