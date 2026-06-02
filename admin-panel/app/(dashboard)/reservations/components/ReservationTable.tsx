"use client";

import Link from "next/link";
import type { ReservationItem } from "@/lib/api/reservations";
import { NoShowButton } from "./NoShowButton";

interface Props {
  items: ReservationItem[];
  isLoading: boolean;
  queryKey: unknown[];
}

const STATUS_BADGE: Record<string, string> = {
  active: "bg-blue-950 text-blue-400 border-blue-900",
  completed: "bg-green-950 text-green-400 border-green-900",
  cancelled: "bg-gray-800 text-gray-400 border-gray-700",
  expired: "bg-red-950 text-red-400 border-red-900",
};

const GENDER_LABEL: Record<string, string> = {
  male: "♂",
  female: "♀",
  not_say: "—",
};

function SkeletonRow() {
  return (
    <tr className="border-t border-gray-800">
      {Array.from({ length: 9 }).map((_, i) => (
        <td key={i} className="px-3 py-3">
          <div className="h-4 bg-gray-800 rounded animate-pulse" />
        </td>
      ))}
    </tr>
  );
}

export function ReservationTable({ items, isLoading, queryKey }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b border-gray-800">
            <th className="px-3 py-2 whitespace-nowrap">Time</th>
            <th className="px-3 py-2 whitespace-nowrap">Channel</th>
            <th className="px-3 py-2 whitespace-nowrap">User</th>
            <th className="px-3 py-2 whitespace-nowrap">Country</th>
            <th className="px-3 py-2 whitespace-nowrap">Gender</th>
            <th className="px-3 py-2 whitespace-nowrap">Score</th>
            <th className="px-3 py-2 whitespace-nowrap">Status</th>
            <th className="px-3 py-2 whitespace-nowrap">No-show</th>
            <th className="px-3 py-2 whitespace-nowrap"></th>
          </tr>
        </thead>
        <tbody>
          {isLoading && items.length === 0
            ? Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} />)
            : items.length === 0
            ? (
              <tr>
                <td colSpan={9} className="text-center py-16 text-gray-500">
                  No reservations found for this date and filters
                </td>
              </tr>
            )
            : items.map((item) => {
                const score = item.user.participation_score;
                const scoreColor =
                  score > 0 ? "text-green-400" : score < 0 ? "text-red-400" : "text-gray-300";

                return (
                  <tr key={item.id} className="border-t border-gray-800 hover:bg-gray-900/50">
                    <td className="px-3 py-2.5 font-mono text-gray-200 whitespace-nowrap">
                      {item.slot.slot_time_local}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <span className="px-2 py-0.5 rounded bg-indigo-950 text-indigo-400 border border-indigo-900 text-xs">
                        {item.channel.name}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <div className="text-white font-medium">{item.user.full_name}</div>
                      <div className="text-xs text-gray-500">#{item.user.public_user_code}</div>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap text-gray-300">
                      {item.user.country
                        ? `${item.user.country.flag_emoji ?? ""} ${item.user.country.name}`.trim()
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-3 py-2.5 text-center text-gray-400">
                      {GENDER_LABEL[item.user.gender ?? ""] ?? "—"}
                    </td>
                    <td className={`px-3 py-2.5 font-bold tabular-nums ${scoreColor}`}>
                      {score > 0 ? `+${score}` : score}
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 text-xs rounded border ${
                          STATUS_BADGE[item.status] ?? "bg-gray-800 text-gray-400 border-gray-700"
                        }`}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <NoShowButton reservation={item} queryKey={queryKey} />
                    </td>
                    <td className="px-3 py-2.5">
                      <Link
                        href={`/users/${item.user.id}`}
                        className="text-gray-500 hover:text-indigo-400 transition-colors"
                        title="View user"
                      >
                        👁
                      </Link>
                    </td>
                  </tr>
                );
              })}
        </tbody>
      </table>
    </div>
  );
}
