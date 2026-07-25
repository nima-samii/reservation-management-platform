import { api } from "@/lib/api";

export interface Channel {
  id: string;
  name: string;
  telegram_channel_id: number;
  invite_link: string | null;
  priority: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateChannelParams {
  name: string;
  telegram_channel_id: number;
  invite_link?: string | null;
}

export interface UpdateChannelParams {
  name?: string;
  invite_link?: string | null;
  is_active?: boolean;
}

export async function getChannels(): Promise<Channel[]> {
  const { data } = await api.get<Channel[]>("/admin/channels");
  return data;
}

export async function createChannel(params: CreateChannelParams): Promise<Channel> {
  const { data } = await api.post<Channel>("/admin/channels", params);
  return data;
}

export async function updateChannel(
  id: string,
  params: UpdateChannelParams
): Promise<Channel> {
  const { data } = await api.patch<Channel>(`/admin/channels/${id}`, params);
  return data;
}

export async function deleteChannel(id: string): Promise<{ id: string; deleted: boolean }> {
  const { data } = await api.delete(`/admin/channels/${id}`);
  return data;
}

export async function moveChannel(
  id: string,
  direction: "up" | "down"
): Promise<Channel> {
  const { data } = await api.post<Channel>(`/admin/channels/${id}/reorder`, { direction });
  return data;
}
