import type { SettingFieldMeta } from "@/lib/api/settings";

const HH_MM_RE = /^([01]\d|2[0-3]):[0-5]\d$/;
const TELEGRAM_CHANNEL_URL_RE = /^https:\/\/t\.me\/.+/;

/**
 * Client-side mirror of the backend's validate_and_coerce() dispatch
 * (app/core/settings_registry.py). Gives immediate inline feedback; the
 * backend 422 response remains the final authority.
 */
export function validateFieldValue(
  meta: SettingFieldMeta,
  value: string | number | boolean | null
): string | null {
  if (meta.type === "bool") return null;

  if (meta.type === "int" || meta.type === "float") {
    if (value === null || value === "" || Number.isNaN(Number(value))) {
      return `${meta.label} must be a number`;
    }
    const num = Number(value);
    if (meta.type === "int" && !Number.isInteger(num)) {
      return `${meta.label} must be a whole number`;
    }
    if (meta.min !== null && num < meta.min) return `Minimum value is ${meta.min}`;
    if (meta.max !== null && num > meta.max) return `Maximum value is ${meta.max}`;
    return null;
  }

  // str fields
  const str = String(value ?? "");
  if (meta.widget === "time") {
    if (!HH_MM_RE.test(str)) return "Expected a 24-hour HH:MM time, e.g. 23:59";
  }
  return null;
}

export function validateMembershipChannelId(value: string | number): string | null {
  const num = Number(value);
  if (!Number.isInteger(num)) return "Channel ID must be a whole number";
  if (num >= 0) return "Telegram channel/supergroup IDs are negative integers";
  return null;
}

export function validateMembershipChannelUrl(value: string): string | null {
  if (!TELEGRAM_CHANNEL_URL_RE.test(value)) {
    return "Expected a URL starting with https://t.me/";
  }
  return null;
}
