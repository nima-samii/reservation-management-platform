import { api } from "@/lib/api";

export interface ReservationRules {
  max_active_reservations: number;
  max_reservation_days_ahead: number;
  channel_capacity_threshold: number;
  same_day_cutoff_hour: number;
  same_day_cancel_cutoff_hour: number;
}

export interface SlotSchedule {
  slot_start_hour: number;
  slot_end_hour: number;
  slot_duration_minutes: number;
  enable_final_midnight_slot: boolean;
  final_slot_time: string;
}

export interface Notifications {
  same_day_reminder_hour: number;
  pre_session_reminder_minutes: number;
}

export interface BroadcastSettings {
  daily_broadcast_hour: number;
  enable_broadcast_auto_pin: boolean;
  delete_previous_broadcast: boolean;
}

export interface AllSettings {
  reservation_rules: ReservationRules;
  slot_schedule: SlotSchedule;
  notifications: Notifications;
  broadcast: BroadcastSettings;
}

export interface SettingsHistoryEntry {
  changed_at: string;
  field: string;
  old_value: string;
  new_value: string;
  changed_by: string;
}

export async function getSettings(): Promise<AllSettings> {
  const { data } = await api.get<AllSettings>("/admin/settings");
  return data;
}

export async function patchSettings(partial: Partial<AllSettings>): Promise<AllSettings> {
  const { data } = await api.patch<AllSettings>("/admin/settings", partial);
  return data;
}

export async function getSettingsHistory(): Promise<SettingsHistoryEntry[]> {
  const { data } = await api.get<SettingsHistoryEntry[]>("/admin/settings/history");
  return data;
}
