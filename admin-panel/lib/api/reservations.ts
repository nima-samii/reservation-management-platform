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

export interface ReservationItem {
  id: string;
  status: string;
  notes: string | null;
  slot: SlotInfo;
  channel: ChannelInfo;
  user: UserInfo;
  no_show_applied: boolean;
}

export type ReservationDetail = ReservationItem;

export interface NoShowResponse {
  reservation_id: string;
  user_id: string;
  new_score: number;
  transaction_id: string;
}

export interface DaySummary {
  total: number;
  active: number;
  completed: number;
  cancelled: number;
  no_show: number;
}

export interface PaginatedReservations {
  items: ReservationItem[];
  total: number;
  page: number;
  pages: number;
  summary: DaySummary;
}

export interface ChannelItem {
  id: string;
  name: string;
  telegram_channel_id: number;
  capacity: number;
  priority: number;
  is_active: boolean;
}

export interface ReservationsParams {
  date?: string;
  date_from?: string;
  date_to?: string;
  channel_id?: string;
  status?: string;
  search?: string;
  page?: number;
  page_size?: number;
}

export interface ExportParams {
  date_from: string;
  date_to: string;
  channel_id?: string;
  status?: string;
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

export async function markNoShow(id: string): Promise<NoShowResponse> {
  const { data } = await api.post<NoShowResponse>(
    `/admin/reservations/${id}/no-show`,
    {}
  );
  return data;
}

export async function getChannels(): Promise<ChannelItem[]> {
  const { data } = await api.get<ChannelItem[]>("/admin/channels");
  return data;
}

export async function exportReservations(params: ExportParams): Promise<void> {
  const q = new URLSearchParams();
  q.set("date_from", params.date_from);
  q.set("date_to", params.date_to);
  if (params.channel_id) q.set("channel_id", params.channel_id);
  if (params.status) q.set("status", params.status);
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
