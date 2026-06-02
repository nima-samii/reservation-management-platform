"use client";

import type { DaySummary } from "@/lib/api/reservations";

interface Props {
  summary: DaySummary;
  onNoShowFilter?: () => void;
}

interface CardProps {
  label: string;
  value: number;
  color: string;
  onClick?: () => void;
}

function Card({ label, value, color, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={`flex-1 min-w-0 bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 ${
        onClick ? "cursor-pointer hover:border-gray-600 transition-colors" : ""
      }`}
    >
      <div className={`text-2xl font-bold tabular-nums ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5 uppercase tracking-wide">{label}</div>
    </div>
  );
}

export function SummaryBar({ summary, onNoShowFilter }: Props) {
  return (
    <div className="flex gap-3 flex-wrap">
      <Card label="Total" value={summary.total} color="text-white" />
      <Card label="Active" value={summary.active} color="text-blue-400" />
      <Card label="Completed" value={summary.completed} color="text-green-400" />
      <Card label="Cancelled" value={summary.cancelled} color="text-gray-400" />
      <Card
        label="No-show"
        value={summary.no_show}
        color="text-red-400"
        onClick={onNoShowFilter}
      />
    </div>
  );
}
