"use client";

import type { AttendanceFilter, DaySummary } from "@/lib/api/reservations";

interface Props {
  summary: DaySummary;
  /** Which attendance filter is active, so the matching card can show it. */
  active?: AttendanceFilter;
  /** Toggle an attendance filter. Passing the active one again clears it. */
  onAttendanceFilter?: (value: AttendanceFilter) => void;
}

interface CardProps {
  label: string;
  value: number;
  color: string;
  title?: string;
  selected?: boolean;
  onClick?: () => void;
}

function Card({ label, value, color, title, selected, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      title={title}
      className={`flex-1 min-w-0 bg-gray-900 border rounded-xl px-4 py-3 ${
        selected ? "border-indigo-500" : "border-gray-800"
      } ${onClick ? "cursor-pointer hover:border-gray-600 transition-colors" : ""}`}
    >
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5 uppercase tracking-wide">
        {label}
      </div>
    </div>
  );
}

export function SummaryBar({ summary, active, onAttendanceFilter }: Props) {
  // Clicking the active card again clears the filter — otherwise the only way
  // back to the full list is the select above, which is easy to miss once the
  // card is highlighted.
  const toggle = (value: AttendanceFilter) => {
    if (!onAttendanceFilter) return;
    onAttendanceFilter(active === value ? "" : value);
  };

  return (
    <div className="flex gap-3 flex-wrap">
      <Card label="Total" value={summary.total} color="text-white" />
      <Card label="Active" value={summary.active} color="text-blue-400" />
      <Card label="Completed" value={summary.completed} color="text-green-400" />
      <Card label="Cancelled" value={summary.cancelled} color="text-gray-400" />
      {/* The work queue. First card an admin should look at, and the reason
          this count exists at all. */}
      <Card
        label="To decide"
        value={summary.awaiting_decision}
        color="text-indigo-400"
        title="Completed sessions with no attendance decision recorded yet"
        selected={active === "pending"}
        onClick={() => toggle("pending")}
      />
      <Card
        label="Attended"
        value={summary.attended}
        color="text-green-400"
        title="Recorded as attended by an admin"
        selected={active === "attended"}
        onClick={() => toggle("attended")}
      />
      {/* Named "Absent", not "No-show": the outcome no longer implies a
          penalty. Counts both an `absent` decision and the retired flag. */}
      <Card
        label="Absent"
        value={summary.no_show}
        color="text-amber-400"
        title="Recorded as not attended — includes penalties applied under the previous system"
        selected={active === "absent"}
        onClick={() => toggle("absent")}
      />
    </div>
  );
}
