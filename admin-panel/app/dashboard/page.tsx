"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import toast from "react-hot-toast";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { getDashboardStats, getActivityData } from "@/lib/api/dashboard";
import { triggerJob } from "@/lib/api/jobs";

const DAYS_OPTIONS = [7, 14, 30] as const;
type Days = (typeof DAYS_OPTIONS)[number];

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full mr-1.5 ${ok ? "bg-green-500" : "bg-red-500"}`}
    />
  );
}

function FillBar({ fill_pct }: { fill_pct: number }) {
  const pct = Math.min(100, Math.round(fill_pct * 100));
  const color =
    pct > 90 ? "bg-red-500" : pct > 70 ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="w-full bg-gray-800 rounded-full h-2">
      <div
        className={`${color} h-2 rounded-full transition-all`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export default function DashboardPage() {
  const [activityDays, setActivityDays] = useState<Days>(7);
  const queryClient = useQueryClient();

  const {
    data: stats,
    isLoading: statsLoading,
    dataUpdatedAt,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ["admin", "dashboard", "stats"],
    queryFn: getDashboardStats,
    refetchInterval: 60_000,
  });

  const { data: activity, isLoading: activityLoading } = useQuery({
    queryKey: ["admin", "dashboard", "activity", activityDays],
    queryFn: () => getActivityData(activityDays),
  });

  const triggerMutation = useMutation({
    mutationFn: (jobId: string) => triggerJob(jobId),
    onSuccess: (_, jobId) => {
      toast.success(`Job "${jobId}" triggered — check logs for result`);
    },
    onError: () => toast.error("Failed to trigger job"),
  });

  const secondsAgo = dataUpdatedAt
    ? Math.floor((Date.now() - dataUpdatedAt) / 1000)
    : null;

  if (statsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-gray-500 animate-pulse">Loading dashboard…</span>
      </div>
    );
  }

  const today = stats?.today;
  const week = stats?.week;
  const system = stats?.system;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Dashboard</h1>
        <div className="flex items-center gap-3">
          {secondsAgo !== null && (
            <span className="text-xs text-gray-500">
              Updated {secondsAgo}s ago
            </span>
          )}
          <button
            onClick={() => refetchStats()}
            className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* ── Left column (wider) ── */}
        <div className="xl:col-span-2 space-y-6">
          {/* Activity chart */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-medium text-gray-300">Activity</h2>
              <div className="flex rounded-lg overflow-hidden border border-gray-700 text-xs">
                {DAYS_OPTIONS.map((d) => (
                  <button
                    key={d}
                    onClick={() => setActivityDays(d)}
                    className={`px-3 py-1.5 transition-colors ${
                      activityDays === d
                        ? "bg-indigo-600 text-white"
                        : "bg-gray-800 text-gray-400 hover:text-white"
                    }`}
                  >
                    {d}d
                  </button>
                ))}
              </div>
            </div>
            {activityLoading ? (
              <div className="h-48 flex items-center justify-center text-gray-600 text-sm animate-pulse">
                Loading chart…
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={activity ?? []} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                  <XAxis
                    dataKey="date"
                    tick={{ fill: "#6b7280", fontSize: 11 }}
                    tickFormatter={(v) => v.slice(5)}
                  />
                  <YAxis tick={{ fill: "#6b7280", fontSize: 11 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                    labelStyle={{ color: "#e5e7eb" }}
                    itemStyle={{ color: "#9ca3af" }}
                  />
                  <Legend wrapperStyle={{ fontSize: 12, color: "#9ca3af" }} />
                  <Line type="monotone" dataKey="total" stroke="#6366f1" strokeWidth={2} dot={false} name="Total" />
                  <Line type="monotone" dataKey="completed" stroke="#22c55e" strokeWidth={2} dot={false} name="Completed" />
                  <Line type="monotone" dataKey="no_show" stroke="#ef4444" strokeWidth={2} dot={false} name="No-show" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Fill rate per channel */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-4">
              Today&apos;s channel fill rate
            </h2>
            {today?.fill_rate_per_channel.length === 0 ? (
              <p className="text-sm text-gray-600">No active channels.</p>
            ) : (
              <div className="space-y-3">
                {today?.fill_rate_per_channel.map((ch) => {
                  const pct = Math.round(ch.fill_pct * 100);
                  return (
                    <div key={ch.channel_id}>
                      <div className="flex justify-between items-center text-xs text-gray-400 mb-1">
                        <span>{ch.channel_name}</span>
                        <span>
                          {ch.booked} / {ch.capacity} slots ({pct}%)
                        </span>
                      </div>
                      <FillBar fill_pct={ch.fill_pct} />
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* ── Right column ── */}
        <div className="space-y-4">
          {/* System status */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">System</h2>
            <ul className="space-y-2 text-sm text-gray-400">
              <li>
                <StatusDot ok={system?.scheduler_running ?? false} />
                Scheduler:{" "}
                <span className={system?.scheduler_running ? "text-green-400" : "text-red-400"}>
                  {system?.scheduler_running ? "Running" : "Stopped"}
                </span>
              </li>
              <li>
                <StatusDot ok={system?.redis_connected ?? false} />
                Redis:{" "}
                <span className={system?.redis_connected ? "text-green-400" : "text-red-400"}>
                  {system?.redis_connected ? "Connected" : "Error"}
                </span>
              </li>
              <li>
                <StatusDot ok={system?.db_connected ?? false} />
                Database:{" "}
                <span className={system?.db_connected ? "text-green-400" : "text-red-400"}>
                  {system?.db_connected ? "Connected" : "Error"}
                </span>
              </li>
              {system?.last_broadcast_at && (
                <li className="pt-1 border-t border-gray-800">
                  <span className="text-gray-500 text-xs">Last broadcast</span>
                  <br />
                  <span className="text-xs">
                    {new Date(system.last_broadcast_at).toLocaleString()}
                  </span>{" "}
                  <span
                    className={`text-xs font-medium ${
                      system.last_broadcast_status === "sent"
                        ? "text-green-400"
                        : "text-red-400"
                    }`}
                  >
                    {system.last_broadcast_status}
                  </span>
                </li>
              )}
            </ul>
          </div>

          {/* Week summary */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">This week</h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-gray-400">
                <span>Total reservations</span>
                <span className="text-white font-medium">{week?.total_reservations ?? 0}</span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>No-show rate</span>
                <span
                  className={`font-medium ${
                    (week?.no_show_rate ?? 0) > 0.1 ? "text-red-400" : "text-green-400"
                  }`}
                >
                  {((week?.no_show_rate ?? 0) * 100).toFixed(1)}%
                </span>
              </div>
              <div className="flex justify-between text-gray-400">
                <span>New users</span>
                <span className="text-white font-medium">{week?.new_users ?? 0}</span>
              </div>
              {(week?.top_countries ?? []).length > 0 && (
                <div className="pt-2 border-t border-gray-800">
                  <p className="text-xs text-gray-500 mb-2">Top countries</p>
                  <ul className="space-y-1">
                    {week!.top_countries.map((c) => (
                      <li key={c.country_name} className="flex justify-between text-xs text-gray-400">
                        <span>
                          {c.flag_emoji && <span className="mr-1">{c.flag_emoji}</span>}
                          {c.country_name}
                        </span>
                        <span>{c.count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>

          {/* Today summary */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">Today</h2>
            <div className="grid grid-cols-2 gap-2 text-xs">
              {[
                { label: "Total", value: today?.total_reservations ?? 0, color: "text-white" },
                { label: "Active", value: today?.active ?? 0, color: "text-indigo-400" },
                { label: "Completed", value: today?.completed ?? 0, color: "text-green-400" },
                { label: "Cancelled", value: today?.cancelled ?? 0, color: "text-gray-400" },
                { label: "No-show", value: today?.no_show ?? 0, color: "text-red-400" },
                { label: "Unique users", value: today?.unique_users ?? 0, color: "text-blue-400" },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-gray-800 rounded-lg p-2">
                  <div className={`text-lg font-semibold ${color}`}>{value}</div>
                  <div className="text-gray-500">{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick actions */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <h2 className="text-sm font-medium text-gray-300 mb-3">Quick actions</h2>
            <div className="space-y-2">
              <button
                onClick={() => triggerMutation.mutate("slot_generation")}
                disabled={triggerMutation.isPending}
                className="w-full text-left px-3 py-2 text-sm text-gray-300 bg-gray-800 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors disabled:opacity-50"
              >
                ⚡ Trigger slot generation
              </button>
              <a
                href="/broadcast"
                className="block px-3 py-2 text-sm text-gray-300 bg-gray-800 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors text-center"
              >
                📢 Send custom message
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
