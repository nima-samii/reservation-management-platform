"use client";

import { useQuery } from "@tanstack/react-query";
import { getReservationTimeline, type TimelineEvent } from "@/lib/api/reservations";

interface Props {
  reservationId: string;
}

// Visual treatment per event type: dot color + emoji marker.
const EVENT_STYLE: Record<string, { dot: string; icon: string }> = {
  reservation_created: { dot: "bg-indigo-500", icon: "📅" },
  score_awarded: { dot: "bg-green-500", icon: "⭐" },
  // A deduction or a zero-delta review. Not styled as a loss — an adjustment
  // is a correction, not a verdict on the user.
  score_adjusted: { dot: "bg-gray-500", icon: "✎" },
  notification_sent: { dot: "bg-sky-500", icon: "✉️" },
  attendance_recorded: { dot: "bg-purple-500", icon: "🗒️" },
  no_show_applied: { dot: "bg-amber-500", icon: "⚠️" },
  reservation_cancelled: { dot: "bg-red-500", icon: "🚫" },
};

const DEFAULT_STYLE = { dot: "bg-gray-500", icon: "•" };

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function metaString(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function EventMeta({ event }: { event: TimelineEvent }) {
  const m = event.metadata ?? {};
  const lines: { label: string; value: string }[] = [];

  if (event.type === "reservation_cancelled") {
    const by = metaString(m.cancelled_by);
    if (by) lines.push({ label: "By", value: by });
    const reason = metaString(m.reason);
    if (reason) lines.push({ label: "Reason", value: reason });
  } else if (event.type === "no_show_applied") {
    const admin = metaString(m.admin);
    if (admin) lines.push({ label: "By", value: admin });
    const penalty = metaString(m.penalty);
    if (penalty) lines.push({ label: "Penalty", value: penalty });
  } else if (event.type === "attendance_recorded") {
    const admin = metaString(m.admin);
    if (admin) lines.push({ label: "By", value: admin });
    // The explanation is the point of the event — it is what the user was
    // sent, and the only record of why this score and not another.
    const reason = metaString(m.reason);
    if (reason) lines.push({ label: "Explanation", value: reason });
  } else if (event.type === "score_adjusted") {
    const reason = metaString(m.reason);
    if (reason) lines.push({ label: "Reason", value: reason });
  } else if (event.type === "notification_sent") {
    const status = metaString(m.status);
    if (status && status !== "sent") lines.push({ label: "Status", value: status });
  } else if (event.type === "reservation_created") {
    const admin = metaString(m.admin);
    if (admin) lines.push({ label: "By", value: admin });
  }

  if (lines.length === 0) return null;

  return (
    <dl className="mt-1.5 space-y-0.5">
      {lines.map((l) => (
        <div key={l.label} className="flex gap-2 text-xs">
          <dt className="text-gray-500">{l.label}:</dt>
          <dd className="text-gray-300 break-words">{l.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ReservationTimeline({ reservationId }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "reservation-timeline", reservationId],
    queryFn: () => getReservationTimeline(reservationId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4 animate-pulse">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex gap-3">
            <div className="w-3 h-3 rounded-full bg-gray-700 mt-1 flex-shrink-0" />
            <div className="flex-1 space-y-1.5">
              <div className="h-4 bg-gray-800 rounded w-1/3" />
              <div className="h-3 bg-gray-800 rounded w-1/4" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="text-sm text-red-400">Failed to load timeline.</p>;
  }

  const events = data ?? [];

  if (events.length === 0) {
    return (
      <p className="text-sm text-gray-500">No timeline events for this reservation.</p>
    );
  }

  return (
    <ol className="relative">
      {events.map((event, i) => {
        const style = EVENT_STYLE[event.type] ?? DEFAULT_STYLE;
        const isLast = i === events.length - 1;
        return (
          <li key={`${event.type}-${event.timestamp}-${i}`} className="flex gap-3 pb-5 last:pb-0">
            {/* Marker + connecting line */}
            <div className="flex flex-col items-center flex-shrink-0">
              <span
                className={`w-3 h-3 rounded-full ${style.dot} ring-4 ring-gray-900 z-10`}
                aria-hidden
              />
              {!isLast && <span className="w-px flex-1 bg-gray-700 mt-1" />}
            </div>
            {/* Content */}
            <div className="flex-1 min-w-0 -mt-0.5">
              <div className="text-sm font-medium text-white flex items-center gap-1.5">
                <span aria-hidden>{style.icon}</span>
                <span>{event.title}</span>
              </div>
              <time className="text-xs text-gray-500 tabular-nums">
                {formatTimestamp(event.timestamp)}
              </time>
              <EventMeta event={event} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
