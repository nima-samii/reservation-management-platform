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
  | "draft"
  | "pending"
  | "scheduled"
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
  media_type: "text" | "photo" | "document";
  total_recipients: number;
  success_count: number;
  failed_count: number;
  blocked_count: number;
  scheduled_for: string | null;
  template_id: string | null;
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

// ── Sprint 3: media / templates / scheduling ────────────────────────────────

export type MediaKind = "text" | "photo" | "document";
export type ParseMode = "HTML" | "Markdown" | "plain";

export interface RecurrenceSpec {
  frequency: "daily" | "weekly" | "monthly";
  interval: number;
  day_of_week?: number | null;
  day_of_month?: number | null;
  time_of_day?: string | null; // "HH:MM" local time
}

export interface RecurringRule {
  id: string;
  broadcast_id: string;
  frequency: "daily" | "weekly" | "monthly";
  interval: number;
  day_of_week: number | null;
  day_of_month: number | null;
  time_of_day: string;
  next_run_at: string;
  is_active: boolean;
  message_preview: string;
  media_type: MediaKind;
  audience_type: string;
}

export interface CreateBroadcastParams {
  message?: string;
  parse_mode: ParseMode;
  audience_type?: UserAudience;
  filters?: SegmentFilter;
  media_type?: MediaKind;
  media_file_id?: string | null;
  template_id?: string;
  scheduled_for?: string;
  save_as_draft?: boolean;
  recurrence?: RecurrenceSpec;
}

export interface BroadcastTemplate {
  id: string;
  name: string;
  description: string | null;
  message: string;
  parse_mode: ParseMode;
  media_type: MediaKind;
  media_file_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateInput {
  name: string;
  description?: string | null;
  message: string;
  parse_mode: ParseMode;
  media_type: MediaKind;
  media_file_id?: string | null;
}

export async function createUserBroadcast(
  params: CreateBroadcastParams
): Promise<UserBroadcastCreateResult> {
  const { data } = await api.post<UserBroadcastCreateResult>(
    "/admin/broadcast/users",
    params
  );
  return data;
}

export async function updateDraft(
  id: string,
  params: Partial<CreateBroadcastParams>
): Promise<UserBroadcastCreateResult> {
  const { data } = await api.patch<UserBroadcastCreateResult>(
    `/admin/broadcast/users/${id}`,
    params
  );
  return data;
}

export async function sendDraft(id: string): Promise<UserBroadcastCreateResult> {
  const { data } = await api.post<UserBroadcastCreateResult>(
    `/admin/broadcast/users/${id}/send`,
    {}
  );
  return data;
}

export async function uploadMedia(
  file: File,
  media_type: "photo" | "document"
): Promise<{ media_type: MediaKind; media_file_id: string }> {
  const form = new FormData();
  form.append("media_type", media_type);
  form.append("file", file);
  const { data } = await api.post("/admin/broadcast/media", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getTemplates(): Promise<BroadcastTemplate[]> {
  const { data } = await api.get<BroadcastTemplate[]>("/admin/broadcast/templates");
  return data;
}

export async function createTemplate(input: TemplateInput): Promise<BroadcastTemplate> {
  const { data } = await api.post<BroadcastTemplate>("/admin/broadcast/templates", input);
  return data;
}

export async function updateTemplate(
  id: string,
  input: Partial<TemplateInput>
): Promise<BroadcastTemplate> {
  const { data } = await api.put<BroadcastTemplate>(`/admin/broadcast/templates/${id}`, input);
  return data;
}

export async function deleteTemplate(id: string): Promise<void> {
  await api.delete(`/admin/broadcast/templates/${id}`);
}

export async function getRecurringRules(): Promise<RecurringRule[]> {
  const { data } = await api.get<RecurringRule[]>("/admin/broadcast/recurring");
  return data;
}

export async function deactivateRecurringRule(id: string): Promise<void> {
  await api.delete(`/admin/broadcast/recurring/${id}`);
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
