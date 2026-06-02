"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { exportReservations, getReservations, getChannels } from "@/lib/api/reservations";

function toDateString(d: Date): string {
  return d.toISOString().slice(0, 10);
}

interface Props {
  onClose: () => void;
}

export function ExportModal({ onClose }: Props) {
  const today = toDateString(new Date());
  const sevenDaysAgo = toDateString(new Date(Date.now() - 6 * 86400_000));

  const [dateFrom, setDateFrom] = useState(sevenDaysAgo);
  const [dateTo, setDateTo] = useState(today);
  const [channelId, setChannelId] = useState("");
  const [status, setStatus] = useState("");
  const [format, setFormat] = useState<"csv" | "json">("csv");
  const [isExporting, setIsExporting] = useState(false);

  const daysDiff =
    dateFrom && dateTo
      ? Math.floor(
          (new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / 86400_000
        )
      : 0;
  const overLimit = daysDiff > 90;

  const { data: channels } = useQuery({
    queryKey: ["admin", "channels"],
    queryFn: getChannels,
    staleTime: 10 * 60 * 1000,
  });

  const { data: preview } = useQuery({
    queryKey: ["admin", "reservations-export-preview", dateFrom, dateTo, channelId, status],
    queryFn: () =>
      getReservations({
        date_from: dateFrom,
        date_to: dateTo,
        channel_id: channelId || undefined,
        status: status || undefined,
        page_size: 1,
      }),
    enabled: !!dateFrom && !!dateTo && !overLimit,
  });

  async function handleExport() {
    if (overLimit) return;
    setIsExporting(true);
    try {
      await exportReservations({
        date_from: dateFrom,
        date_to: dateTo,
        channel_id: channelId || undefined,
        status: status || undefined,
        format,
      });
    } catch (err: any) {
      toast.error(err?.message ?? "Export failed");
    } finally {
      setIsExporting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-md w-full shadow-2xl space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">Export Reservations</h3>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white text-lg leading-none"
          >
            ✕
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
        </div>

        {overLimit && (
          <p className="text-xs text-red-400">
            Range exceeds 90 days. Please narrow the date range.
          </p>
        )}

        <div>
          <label className="block text-xs text-gray-500 mb-1">Channel (optional)</label>
          <select
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">All channels</option>
            {channels?.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">Status (optional)</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
            <option value="expired">Expired</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">Format</label>
          <div className="flex gap-2">
            {(["csv", "json"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={`px-4 py-1.5 text-sm rounded-md border transition-colors ${
                  format === f
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-gray-800 text-gray-400 border-gray-700 hover:text-white"
                }`}
              >
                {f.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {preview && !overLimit && (
          <p className="text-xs text-gray-400">
            ~<span className="text-white font-medium">{preview.total}</span> reservations
            will be exported
          </p>
        )}

        <div className="flex gap-3 justify-end pt-1">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleExport}
            disabled={isExporting || overLimit || !dateFrom || !dateTo}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isExporting ? "Exporting…" : "Export"}
          </button>
        </div>
      </div>
    </div>
  );
}
