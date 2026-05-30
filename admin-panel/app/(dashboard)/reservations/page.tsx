"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, useCallback } from "react";
import { getReservations, getChannels } from "@/lib/api/reservations";
import { SummaryBar } from "./components/SummaryBar";
import { ReservationTable } from "./components/ReservationTable";
import { ExportModal } from "./components/ExportModal";

function toDateString(d: Date): string {
  return d.toISOString().slice(0, 10);
}

type DateMode = "single" | "range";
type StatusFilter = "" | "active" | "completed" | "cancelled" | "expired";

export default function ReservationsPage() {
  const today = toDateString(new Date());

  const [dateMode, setDateMode] = useState<DateMode>("single");
  const [singleDate, setSingleDate] = useState(today);
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(today);
  const [channelId, setChannelId] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [page, setPage] = useState(1);
  const [showExport, setShowExport] = useState(false);

  // Debounce search 400ms
  const handleSearchChange = useCallback((val: string) => {
    setSearch(val);
    const t = setTimeout(() => {
      setDebouncedSearch(val);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, []);

  const queryParams = {
    ...(dateMode === "single"
      ? { date: singleDate }
      : { date_from: dateFrom, date_to: dateTo }),
    ...(channelId ? { channel_id: channelId } : {}),
    ...(statusFilter ? { status: statusFilter } : {}),
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    page,
    page_size: 100,
  };

  const queryKey = ["admin", "reservations", queryParams];

  const { data, isLoading, isFetching } = useQuery({
    queryKey,
    queryFn: () => getReservations(queryParams),
    placeholderData: (prev) => prev,
  });

  const { data: channels } = useQuery({
    queryKey: ["admin", "channels"],
    queryFn: getChannels,
    staleTime: 10 * 60 * 1000,
  });

  function prevDay() {
    const d = new Date(singleDate);
    d.setDate(d.getDate() - 1);
    setSingleDate(toDateString(d));
    setPage(1);
  }

  function nextDay() {
    const d = new Date(singleDate);
    d.setDate(d.getDate() + 1);
    setSingleDate(toDateString(d));
    setPage(1);
  }

  const summary = data?.summary ?? {
    total: 0,
    active: 0,
    completed: 0,
    cancelled: 0,
    no_show: 0,
  };

  const totalPages = data?.pages ?? 1;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Reservations</h1>
        <button
          onClick={() => setShowExport(true)}
          className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
        >
          Export ↓
        </button>
      </div>

      {/* Toolbar */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
        {/* Date mode toggle */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex rounded-lg overflow-hidden border border-gray-700 text-xs">
            {(["single", "range"] as DateMode[]).map((m) => (
              <button
                key={m}
                onClick={() => { setDateMode(m); setPage(1); }}
                className={`px-3 py-1.5 transition-colors capitalize ${
                  dateMode === m
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-white"
                }`}
              >
                {m === "single" ? "Single day" : "Date range"}
              </button>
            ))}
          </div>

          {dateMode === "single" ? (
            <div className="flex items-center gap-1">
              <button
                onClick={prevDay}
                className="px-2 py-1.5 text-sm text-gray-400 hover:text-white bg-gray-800 border border-gray-700 rounded-l-md transition-colors"
              >
                ←
              </button>
              <input
                type="date"
                value={singleDate}
                onChange={(e) => { setSingleDate(e.target.value); setPage(1); }}
                className="bg-gray-800 border-y border-gray-700 text-white text-sm px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <button
                onClick={nextDay}
                className="px-2 py-1.5 text-sm text-gray-400 hover:text-white bg-gray-800 border border-gray-700 rounded-r-md transition-colors"
              >
                →
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
                className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
              <span className="text-gray-500 text-sm">–</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
                className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          )}
        </div>

        {/* Filters row */}
        <div className="flex items-center gap-3 flex-wrap">
          <select
            value={channelId}
            onChange={(e) => { setChannelId(e.target.value); setPage(1); }}
            className="bg-gray-800 border border-gray-700 text-sm text-white rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">All channels</option>
            {channels?.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value as StatusFilter); setPage(1); }}
            className="bg-gray-800 border border-gray-700 text-sm text-white rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
            <option value="expired">Expired</option>
          </select>

          <input
            type="search"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            placeholder="Search name or code…"
            className="flex-1 min-w-[180px] bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />

          {isFetching && (
            <span className="text-xs text-gray-500 animate-pulse">Loading…</span>
          )}
        </div>
      </div>

      {/* Summary bar */}
      <SummaryBar
        summary={summary}
        onNoShowFilter={() => {
          setStatusFilter("completed");
          setPage(1);
        }}
      />

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <ReservationTable
          items={data?.items ?? []}
          isLoading={isLoading}
          queryKey={queryKey}
        />
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span>
            Page {page} of {totalPages} · {data?.total ?? 0} total
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-md hover:text-white disabled:opacity-40 transition-colors"
            >
              ← Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-md hover:text-white disabled:opacity-40 transition-colors"
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {showExport && <ExportModal onClose={() => setShowExport(false)} />}
    </div>
  );
}
