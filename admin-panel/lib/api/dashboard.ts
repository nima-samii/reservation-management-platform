import { api } from "@/lib/api";

export interface FillRateChannel {
  channel_id: string;
  channel_name: string;
  capacity: number;
  booked: number;
  fill_pct: number;
}

export interface TopCountry {
  country_name: string;
  flag_emoji: string | null;
  count: number;
}

export interface DashboardStats {
  today: {
    total_reservations: number;
    active: number;
    completed: number;
    cancelled: number;
    no_show: number;
    unique_users: number;
    slots_generated: number;
    fill_rate_per_channel: FillRateChannel[];
  };
  week: {
    total_reservations: number;
    no_show_count: number;
    no_show_rate: number;
    new_users: number;
    top_countries: TopCountry[];
  };
  system: {
    scheduler_running: boolean;
    redis_connected: boolean;
    db_connected: boolean;
    last_broadcast_at: string | null;
    last_broadcast_status: "sent" | "failed" | null;
  };
  _cached_at: string;
}

export interface ActivityDay {
  date: string;
  total: number;
  completed: number;
  cancelled: number;
  no_show: number;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const { data } = await api.get<DashboardStats>("/admin/dashboard/stats");
  return data;
}

export async function getActivityData(days: number = 7): Promise<ActivityDay[]> {
  const { data } = await api.get<ActivityDay[]>("/admin/dashboard/activity", {
    params: { days },
  });
  return data;
}
