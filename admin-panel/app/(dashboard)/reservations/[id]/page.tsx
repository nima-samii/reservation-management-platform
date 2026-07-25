"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getReservation } from "@/lib/api/reservations";
import { ReservationTimeline } from "../components/ReservationTimeline";

const STATUS_BADGE: Record<string, string> = {
  active: "bg-blue-950 text-blue-400 border-blue-900",
  completed: "bg-green-950 text-green-400 border-green-900",
  cancelled: "bg-gray-800 text-gray-400 border-gray-700",
  expired: "bg-red-950 text-red-400 border-red-900",
};

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</dt>
      <dd className="text-sm text-gray-200">{value}</dd>
    </div>
  );
}

export default function ReservationDetailPage() {
  const { id } = useParams<{ id: string }>();

  const { data: res, isLoading, isError } = useQuery({
    queryKey: ["admin", "reservation", id],
    queryFn: () => getReservation(id),
  });

  if (isLoading) {
    return (
      <div className="max-w-3xl mx-auto space-y-6 animate-pulse">
        <div className="h-5 bg-gray-800 rounded w-48" />
        <div className="h-44 bg-gray-800 rounded-xl" />
        <div className="h-64 bg-gray-800 rounded-xl" />
      </div>
    );
  }

  if (isError || !res) {
    return (
      <div className="text-center py-20">
        <div className="text-4xl mb-3">❌</div>
        <div className="text-red-400">Reservation not found</div>
        <Link
          href="/reservations"
          className="text-indigo-400 text-sm mt-4 inline-block hover:text-indigo-300"
        >
          ← Back to reservations
        </Link>
      </div>
    );
  }

  const slotDate = new Date(res.slot.slot_datetime);
  const dateStr = Number.isNaN(slotDate.getTime())
    ? res.slot.slot_datetime
    : slotDate.toLocaleDateString(undefined, {
        weekday: "short",
        year: "numeric",
        month: "short",
        day: "numeric",
      });

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-400 flex items-center gap-2">
        <Link href="/reservations" className="hover:text-white transition-colors">
          Reservations
        </Link>
        <span>›</span>
        <span className="text-white">{res.user.full_name}</span>
      </nav>

      {/* Overview */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-white">Reservation Details</h2>
          <span
            className={`inline-flex items-center px-2.5 py-0.5 text-xs rounded border ${
              STATUS_BADGE[res.status] ?? "bg-gray-800 text-gray-400 border-gray-700"
            }`}
          >
            {res.status}
          </span>
        </div>

        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-4">
          <Field
            label="User"
            value={
              <Link
                href={`/users/${res.user.id}`}
                className="text-indigo-400 hover:text-indigo-300 transition-colors"
              >
                {res.user.full_name}
              </Link>
            }
          />
          <Field label="User code" value={`#${res.user.public_user_code}`} />
          <Field label="Channel" value={res.channel.name} />
          <Field label="Date" value={dateStr} />
          <Field label="Time" value={res.slot.slot_time_local} />
          <Field
            label="Country"
            value={
              res.user.country
                ? `${res.user.country.flag_emoji ?? ""} ${res.user.country.name}`.trim()
                : "—"
            }
          />
          <Field
            label="No-show"
            value={res.no_show_applied ? "Applied" : "—"}
          />
        </dl>
      </section>

      {/* Timeline */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-base font-semibold text-white mb-5">Timeline</h3>
        <ReservationTimeline reservationId={id} />
      </section>
    </div>
  );
}
