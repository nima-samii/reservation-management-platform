import { api } from "@/lib/api";

export type RestartBehavior = "live" | "cache_refresh" | "scheduler_restart" | "restart_required";
export type FieldType = "bool" | "int" | "float" | "str";

export interface SettingChoice {
  value: string;
  label: string;
}

export interface SettingFieldMeta {
  key: string;
  label: string;
  description: string;
  type: FieldType;
  example: unknown;
  min: number | null;
  max: number | null;
  placeholder: string | null;
  restart_behavior: RestartBehavior;
  runtime_safe: boolean;
  widget: string | null;
  // Populated only for `select` fields; the dropdown options come from the
  // backend registry so the UI can never offer a value PATCH would reject.
  choices: SettingChoice[] | null;
}

export interface SettingCategoryMeta {
  key: string;
  label: string;
  fields: SettingFieldMeta[];
}

export type SettingsMetadata = SettingCategoryMeta[];

// category -> { field_key: value }
export type SettingsValues = Record<string, Record<string, string | number | boolean | null>>;

export interface SettingsHistoryEntry {
  changed_at: string;
  field: string;
  old_value: string;
  new_value: string;
  changed_by: string;
}

export interface MembershipChannel {
  id: number;
  url: string;
}

export async function getSettingsMetadata(): Promise<SettingsMetadata> {
  const { data } = await api.get<SettingsMetadata>("/admin/settings/metadata");
  return data;
}

export async function getSettings(): Promise<SettingsValues> {
  const { data } = await api.get<SettingsValues>("/admin/settings");
  return data;
}

export async function patchSettings(partial: SettingsValues): Promise<SettingsValues> {
  const { data } = await api.patch<SettingsValues>("/admin/settings", partial);
  return data;
}

export async function getSettingsHistory(): Promise<SettingsHistoryEntry[]> {
  const { data } = await api.get<SettingsHistoryEntry[]>("/admin/settings/history");
  return data;
}

export async function getMembershipChannels(): Promise<MembershipChannel[]> {
  const { data } = await api.get<MembershipChannel[]>("/admin/settings/membership-channels");
  return data;
}

export async function putMembershipChannels(
  channels: MembershipChannel[]
): Promise<MembershipChannel[]> {
  const { data } = await api.put<MembershipChannel[]>("/admin/settings/membership-channels", {
    channels,
  });
  return data;
}
