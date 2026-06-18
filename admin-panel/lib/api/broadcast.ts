import { api } from "@/lib/api";

export interface ManualBroadcastParams {
  channel_ids: string[];
  message: string;
  parse_mode: "HTML" | "Markdown" | "plain";
}

export interface BroadcastChannelResult {
  channel_id: string;
  channel_name: string | null;
  success: boolean;
  error: string | null;
  telegram_message_id?: number | null;
}

export interface TriggerDailyParams {
  channel_ids: string[] | null;
}

export interface BroadcastLogItem {
  id: string;
  channel_id: string | null;
  channel_name: string | null;
  broadcast_date: string;
  status: "sent" | "failed";
  telegram_message_id: number | null;
  error_message: string | null;
  sent_at: string;
}

export interface PaginatedBroadcastLogs {
  items: BroadcastLogItem[];
  total: number;
  page: number;
  pages: number;
}

export async function sendManualBroadcast(
  params: ManualBroadcastParams
): Promise<BroadcastChannelResult[]> {
  const { data } = await api.post<BroadcastChannelResult[]>(
    "/admin/broadcast/manual",
    params
  );
  return data;
}

export async function triggerDailyBroadcast(
  params: TriggerDailyParams
): Promise<BroadcastChannelResult[]> {
  const { data } = await api.post<BroadcastChannelResult[]>(
    "/admin/broadcast/trigger-daily",
    params
  );
  return data;
}

export async function getBroadcastLogs(params: {
  date?: string;
  channel_id?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedBroadcastLogs> {
  const { data } = await api.get<PaginatedBroadcastLogs>("/admin/broadcast/logs", {
    params,
  });
  return data;
}

// ── User broadcasts ─────────────────────────────────────────────────────────

export type UserAudience =
  | "all_users"
  | "active_users"
  | "users_with_reservations";

export type UserBroadcastStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed";

export interface UserBroadcastCreateParams {
  audience_type: UserAudience;
  message: string;
  parse_mode: "HTML" | "Markdown" | "plain";
}

export interface UserBroadcastCreateResult {
  id: string;
  status: UserBroadcastStatus;
  audience_type: UserAudience;
  total_recipients: number;
}

export interface UserBroadcastProgress {
  id: string;
  status: UserBroadcastStatus;
  audience_type: UserAudience;
  total_recipients: number;
  success_count: number;
  failed_count: number;
  blocked_count: number;
  progress_percent: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface UserBroadcastHistoryItem {
  id: string;
  audience_type: UserAudience;
  status: UserBroadcastStatus;
  message: string;
  total_recipients: number;
  success_count: number;
  failed_count: number;
  blocked_count: number;
  created_at: string;
  completed_at: string | null;
}

export interface PaginatedUserBroadcasts {
  items: UserBroadcastHistoryItem[];
  total: number;
  page: number;
  pages: number;
}

export const AUDIENCE_LABELS: Record<UserAudience, string> = {
  all_users: "All Users",
  active_users: "Active Users",
  users_with_reservations: "Users With Reservations",
};

export async function previewUserAudience(
  audience_type: UserAudience
): Promise<{ count: number }> {
  const { data } = await api.post<{ count: number }>(
    "/admin/broadcast/users/preview",
    { audience_type }
  );
  return data;
}

export async function createUserBroadcast(
  params: UserBroadcastCreateParams
): Promise<UserBroadcastCreateResult> {
  const { data } = await api.post<UserBroadcastCreateResult>(
    "/admin/broadcast/users",
    params
  );
  return data;
}

export async function getUserBroadcast(
  id: string
): Promise<UserBroadcastProgress> {
  const { data } = await api.get<UserBroadcastProgress>(
    `/admin/broadcast/users/${id}`
  );
  return data;
}

export async function getUserBroadcasts(params: {
  page?: number;
  page_size?: number;
}): Promise<PaginatedUserBroadcasts> {
  const { data } = await api.get<PaginatedUserBroadcasts>(
    "/admin/broadcast/users",
    { params }
  );
  return data;
}
