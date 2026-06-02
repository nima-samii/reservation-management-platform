import { api } from "@/lib/api";

export interface ScheduleEvent {
  id: string;
  channel_id: string | null;
  channel_name: string | null;
  event_date: string;
  title: string;
  sort_order: number;
  is_active: boolean;
}

export interface CreateEventParams {
  channel_id: string | null;
  event_date: string;
  title: string;
  sort_order: number;
  is_active: boolean;
}

export interface PatchEventParams {
  title?: string;
  sort_order?: number;
  is_active?: boolean;
}

export async function getEvents(params: {
  date_from?: string;
  date_to?: string;
  channel_id?: string;
}): Promise<ScheduleEvent[]> {
  const { data } = await api.get<ScheduleEvent[]>("/admin/schedule-events", { params });
  return data;
}

export async function createEvent(params: CreateEventParams): Promise<ScheduleEvent> {
  const { data } = await api.post<ScheduleEvent>("/admin/schedule-events", params);
  return data;
}

export async function patchEvent(id: string, params: PatchEventParams): Promise<ScheduleEvent> {
  const { data } = await api.patch<ScheduleEvent>(`/admin/schedule-events/${id}`, params);
  return data;
}

export async function deleteEvent(id: string): Promise<{ id: string; deleted: boolean }> {
  const { data } = await api.delete(`/admin/schedule-events/${id}`);
  return data;
}
