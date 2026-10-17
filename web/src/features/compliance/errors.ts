import { ApiError } from "@/app/api/client";

/** Plain-English copy for the signing dialog. Known codes use a fixed sentence so the UI does not depend on wording drift. */
export function signErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return err instanceof Error ? err.message : String(err);
  switch (err.code) {
    case "self_approval_forbidden":
      return "Authors can't approve their own work.";
    case "out_of_order":
      return err.message || "Signatures must follow the required order.";
    case "account_locked":
      return err.message || "Signing is locked after too many wrong PINs.";
    case "invalid_credential":
      return "Wrong PIN — the signature was not recorded.";
    case "role_not_permitted":
      return err.message || "This role cannot sign that meaning.";
    case "record_changed":
      return err.message || "The record changed after it was submitted.";
    default:
      return err.message;
  }
}
