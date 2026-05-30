"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { getScoreHistory } from "@/lib/api/users";

interface Props {
  userId: string;
}

const TYPE_LABELS: Record<string, string> = {
  reservation_reward: "Reservation",
  reservation_cancellation: "Cancellation",
  no_show_penalty: "No-show",
  admin_adjustment: "Admin",
};

const TYPE_COLORS: Record<string, string> = {
  reservation_reward: "bg-green-950 text-green-400 border-green-900",
  reservation_cancellation: "bg-yellow-950 text-yellow-400 border-yellow-900",
  no_show_penalty: "bg-red-950 text-red-400 border-red-900",
  admin_adjustment: "bg-indigo-950 text-indigo-400 border-indigo-900",
};

function TypeBadge({ type }: { type: string }) {
  const label = TYPE_LABELS[type] ?? type;
  const cls = TYPE_COLORS[type] ?? "bg-gray-800 text-gray-400 border-gray-700";
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs border ${cls} whitespace-nowrap`}>
      {label}
    </span>
  );
}

export function ScoreHistory({ userId }: Props) {
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "score-history", userId, page],
    queryFn: () => getScoreHistory(userId, page, 30),
  });

  if (isLoading) {
    return (
      <div className="space-y-2 animate-pulse">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-10 bg-gray-800 rounded" />
        ))}
      </div>
    );
  }

  if (!data || data.items.length === 0) {
    return (
      <div className="text-gray-500 text-sm py-6 text-center">No score history yet</div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="pb-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                Date
              </th>
              <th className="pb-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                Type
              </th>
              <th className="pb-2 text-right text-xs font-medium text-gray-500 uppercase tracking-wide">
                Delta
              </th>
              <th className="pb-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wide pl-4">
                Reason
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {data.items.map((tx) => (
              <tr key={tx.id}>
                <td className="py-2.5 text-gray-400 whitespace-nowrap text-xs">
                  {new Date(tx.created_at).toLocaleString()}
                </td>
                <td className="py-2.5">
                  <TypeBadge type={tx.transaction_type} />
                </td>
                <td
                  className={`py-2.5 text-right font-medium ${
                    tx.delta > 0 ? "text-green-400" : "text-red-400"
                  }`}
                >
                  {tx.delta > 0 ? "+" : ""}
                  {tx.delta}
                </td>
                <td className="py-2.5 pl-4 text-gray-400 text-xs">{tx.reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.pages > 1 && (
        <div className="mt-4 flex items-center justify-between text-sm text-gray-400">
          <span>
            Page {page} of {data.pages}
          </span>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 rounded-md bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
            >
              ← Prev
            </button>
            <button
              disabled={page >= data.pages}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 rounded-md bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors text-xs"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
