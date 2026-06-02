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
