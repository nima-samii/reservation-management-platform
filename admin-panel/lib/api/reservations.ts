import { api } from "../api";
import { getCookie } from "../auth";

export interface SlotInfo {
  id: string;
  slot_datetime: string;
  slot_time_local: string;
}

export interface ChannelInfo {
  id: string;
  name: string;
}

export interface CountryInfo {
  name: string;
  flag_emoji: string | null;
}

export interface UserInfo {
  id: string;
  public_user_code: string;
  full_name: string;
  gender: string | null;
  country: CountryInfo | null;
  participation_score: number;
}

export type AttendanceStatus = "attended" | "absent";

export interface ReservationItem {
  id: string;
  status: string;
  notes: string | null;
  slot: SlotInfo;
  channel: ChannelInfo;
  user: UserInfo;

  // The retired no-show penalty only. Always meant -1 and cannot be
  // re-decided, so it is rendered as history, never as an outcome an admin
  // chose.
  no_show_applied: boolean;

  // The attendance decision. All five are null until an admin records one —
  // which is why `attendance_score_delta` is `number | null` and not `number`:
  // 0 is a real decision ("attended, worth nothing") and must not look like
  // "not judged yet".
  attendance_status: AttendanceStatus | null;
  attendance_score_delta: number | null;
  attendance_reason: string | null;
  attendance_marked_by: string | null;
  attendance_marked_at: string | null;
}

export type ReservationDetail = ReservationItem;

export interface TimelineEvent {
  type: string;
  title: string;
  timestamp: string;
  metadata: Record<string, unknown>;
}

export interface RecordAttendanceBody {
  attendance_status: AttendanceStatus;
  score_delta: number;
  reason: string;
}

export interface AttendanceResponse {
  reservation_id: string;
  user_id: string;
  attendance_status: AttendanceStatus;
  score_delta: number;
  reason: string;
  new_score: number;
  transaction_id: string;
  marked_by: string;
  marked_at: string;
}

// Mirrors ATTENDANCE_SCORE_LIMIT / ATTENDANCE_REASON_MAX in
// app/services/reservation.py. Duplicated because the panel is a separate
// build with no access to them; the server re-checks both and is the
// authority, so the worst a drift can do is a 422 the modal already renders.
export const ATTENDANCE_SCORE_LIMIT = 1000;
export const ATTENDANCE_REASON_MAX = 256;

export interface DaySummary {
  total: number;
  active: number;
  completed: number;
  cancelled: number;
  // "Recorded as absent" under either system — the retired penalty flag or an
  // `absent` decision. Kept under the old name on the wire.
  no_show: number;
  attended: number;
  // Completed, unjudged, not already scored by the retired penalty.
  awaiting_decision: number;
}

export type AttendanceFilter = "" | "pending" | "decided" | "attended" | "absent";

export interface PaginatedReservations {
  items: ReservationItem[];
  total: number;
  page: number;
  pages: number;
  summary: DaySummary;
}

// Mirrors ChannelOut from /admin/channels. `capacity` used to be listed here
// but the endpoint has never returned it — the Channel.capacity column is
// deprecated and a channel's real daily capacity is the number of slots
// generated for it that day.
export interface ChannelItem {
  id: string;
  name: string;
  telegram_channel_id: number;
  priority: number;
  is_active: boolean;
}

export interface ReservationsParams {
  date?: string;
  date_from?: string;
  date_to?: string;
  channel_id?: string;
  status?: string;
  attendance?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

export interface ExportParams {
  date_from: string;
  date_to: string;
  channel_id?: string;
  status?: string;
  attendance?: string;
  format?: "csv" | "json";
}

export async function getReservations(
  params: ReservationsParams = {}
): Promise<PaginatedReservations> {
  const q = new URLSearchParams();
  if (params.date) q.set("date", params.date);
  if (params.date_from) q.set("date_from", params.date_from);
  if (params.date_to) q.set("date_to", params.date_to);
  if (params.channel_id) q.set("channel_id", params.channel_id);
  if (params.status) q.set("status", params.status);
  if (params.attendance) q.set("attendance", params.attendance);
  if (params.search) q.set("search", params.search);
  if (params.page) q.set("page", String(params.page));
  if (params.page_size) q.set("page_size", String(params.page_size));
  const { data } = await api.get<PaginatedReservations>(`/admin/reservations?${q}`);
  return data;
}

export async function getReservation(id: string): Promise<ReservationDetail> {
  const { data } = await api.get<ReservationDetail>(`/admin/reservations/${id}`);
  return data;
}

export async function getReservationTimeline(
  id: string
): Promise<TimelineEvent[]> {
  const { data } = await api.get<TimelineEvent[]>(
    `/admin/reservations/${id}/timeline`
  );
  return data;
}

export async function cancelReservation(
  id: string,
  reason?: string
): Promise<ReservationDetail> {
  const { data } = await api.post<ReservationDetail>(
    `/admin/reservations/${id}/cancel`,
    { reason: reason?.trim() ? reason.trim() : null }
  );
  return data;
}

/** Record an attendance decision and the score it carries.
 *
 * Replaces `markNoShow`, which posted to the now-deprecated `/no-show`
 * endpoint and always meant -1. That function is gone rather than kept
 * alongside: the two mechanisms score the same session and the server refuses
 * whichever comes second, so a panel that could still reach the old one would
 * only ever produce a 409 an admin cannot act on.
 *
 * One decision per reservation, ever. Corrections go through an admin score
 * adjustment on the user.
 */
export async function recordAttendance(
  id: string,
  body: RecordAttendanceBody
): Promise<AttendanceResponse> {
  const { data } = await api.post<AttendanceResponse>(
    `/admin/reservations/${id}/attendance`,
    body
  );
  return data;
}

export async function getChannels(): Promise<ChannelItem[]> {
  const { data } = await api.get<ChannelItem[]>("/admin/channels");
  return data;
}

export async function getAvailableSlots(
  channelId: string,
  date: string
): Promise<SlotInfo[]> {
  const q = new URLSearchParams({ channel_id: channelId, date });
  const { data } = await api.get<SlotInfo[]>(
    `/admin/reservations/available-slots?${q}`
  );
  return data;
}

export async function createReservation(body: {
  user_id: string;
  slot_id: string;
}): Promise<ReservationDetail> {
  const { data } = await api.post<ReservationDetail>("/admin/reservations", body);
  return data;
}

export async function exportReservations(params: ExportParams): Promise<void> {
  const q = new URLSearchParams();
  q.set("date_from", params.date_from);
  q.set("date_to", params.date_to);
  if (params.channel_id) q.set("channel_id", params.channel_id);
  if (params.status) q.set("status", params.status);
  if (params.attendance) q.set("attendance", params.attendance);
  q.set("format", params.format ?? "csv");

  const token = getCookie("admin_access_token");
  const response = await fetch(`/api/admin/reservations/export?${q}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Export failed");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const ext = params.format === "json" ? "json" : "csv";
  a.download = `reservations_${params.date_from}_${params.date_to}.${ext}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
