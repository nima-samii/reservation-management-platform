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
  audience_type: string;
  message: string;
  parse_mode: "HTML" | "Markdown" | "plain";
}

export interface UserBroadcastCreateResult {
  id: string;
  status: UserBroadcastStatus;
  audience_type: string;
  total_recipients: number;
}

export interface UserBroadcastProgress {
  id: string;
  status: UserBroadcastStatus;
  audience_type: string;
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
  audience_type: string;
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

export const AUDIENCE_LABELS: Record<string, string> = {
  all_users: "All Users",
  active_users: "Active Users",
  users_with_reservations: "Users With Reservations",
  custom: "Custom Segment",
};

// ── Sprint 2: advanced segmentation ─────────────────────────────────────────

export type ReservationStatus = "active" | "completed" | "cancelled" | "expired";
export type Gender = "male" | "female" | "not_say";

export interface SegmentFilter {
  score?: { min?: number | null; max?: number | null } | null;
  reservation_statuses?: ReservationStatus[] | null;
  has_no_show?: boolean | null;
  has_username?: boolean | null;
  country_ids?: string[] | null;
  genders?: Gender[] | null;
  created_from?: string | null;
  created_to?: string | null;
}

export interface AudiencePreview {
  count: number;
  with_username: number;
  without_username: number;
  avg_score: number;
}

// A preview/create request is either a quick segment or an advanced filter.
export type SegmentRequest =
  | { audience_type: UserAudience }
  | { filters: SegmentFilter };

export async function previewUserAudience(
  req: SegmentRequest
): Promise<AudiencePreview> {
  const { data } = await api.post<AudiencePreview>(
    "/admin/broadcast/users/preview",
    req
  );
  return data;
}

export async function createUserBroadcast(
  params: { message: string; parse_mode: "HTML" | "Markdown" | "plain" } & SegmentRequest
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
