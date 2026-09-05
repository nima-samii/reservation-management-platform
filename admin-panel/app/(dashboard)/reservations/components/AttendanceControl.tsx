"use client";

import { useState } from "react";
import type { AttendanceStatus, ReservationItem } from "@/lib/api/reservations";
import { AttendanceModal } from "./AttendanceModal";

interface Props {
  reservation: ReservationItem;
  queryKey: unknown[];
}

/** Formats a recorded score. `0` is a real decision, so it renders as "0"
 *  rather than being hidden or shown as "+0". */
function scoreLabel(delta: number): string {
  return delta > 0 ? `+${delta}` : String(delta);
}

/** Replaces NoShowButton. The old control was a single confirm dialog that
 *  always deducted 1 point; this one asks for the two things that are now
 *  independent — what happened, and what it was worth — plus the explanation
 *  the user is sent.
 *
 *  Five states, and telling them apart is most of the job:
 *    1. decided            → the outcome and its score, as a badge
 *    2. legacy penalty     → history, not a decision anyone can revisit
 *    3. completed, unjudged→ the two actions
 *    4. passed but ACTIVE  → explain the wait, do not look broken
 *    5. anything else      → nothing to do yet
 */
export function AttendanceControl({ reservation, queryKey }: Props) {
  const [pendingOutcome, setPendingOutcome] = useState<AttendanceStatus | null>(
    null
  );

  // ── 1. A decision exists ────────────────────────────────────────────────
  if (reservation.attendance_status) {
    const attended = reservation.attendance_status === "attended";
    const delta = reservation.attendance_score_delta ?? 0;
    const tooltip = [
      reservation.attendance_reason,
      reservation.attendance_marked_by
        ? `— ${reservation.attendance_marked_by}`
        : null,
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <span
        title={tooltip || undefined}
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs rounded border ${
          attended
            ? "bg-green-950 text-green-400 border-green-900"
            : "bg-amber-950 text-amber-400 border-amber-900"
        }`}
      >
        <span aria-hidden>{attended ? "✓" : "✕"}</span>
        <span>{attended ? "Attended" : "Absent"}</span>
        <span className="text-gray-400 tabular-nums">{scoreLabel(delta)}</span>
      </span>
    );
  }

  // ── 2. The retired penalty ──────────────────────────────────────────────
  if (reservation.no_show_applied) {
    return (
      <span
        title="Scored under the previous system, which always deducted 1 point. It cannot be re-decided; a correction goes through a score adjustment on the user."
        className="inline-flex items-center px-2 py-0.5 text-xs rounded bg-gray-800 text-gray-400 border border-gray-700"
      >
        No-show (legacy)
      </span>
    );
  }

  // ── 4. The session has passed but the lifecycle job has not run yet ─────
  // A reservation is promoted to COMPLETED at :00/:30, so for up to half an
  // hour after the slot there is genuinely nothing to record. Saying so beats
  // an empty cell that reads as a bug.
  if (reservation.status === "active") {
    const slotPassed = new Date(reservation.slot.slot_datetime) < new Date();
    if (slotPassed) {
      return (
        <span
          title="Reservations are marked completed by a job that runs at :00 and :30. Attendance can be recorded once that has happened — usually within half an hour of the session."
          className="text-xs text-gray-500"
        >
          Awaiting completion
        </span>
      );
    }
    return <span className="text-gray-600">—</span>;
  }

  // ── 5. Cancelled or expired: never attended, never will be ──────────────
  if (reservation.status !== "completed") {
    return <span className="text-gray-600">—</span>;
  }

  // ── 3. Completed and unjudged: the two actions ──────────────────────────
  return (
    <>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => setPendingOutcome("attended")}
          className="text-xs px-2 py-1 bg-green-900/40 text-green-400 border border-green-800 rounded hover:bg-green-900 transition-colors whitespace-nowrap"
        >
          Attended
        </button>
        <button
          onClick={() => setPendingOutcome("absent")}
          className="text-xs px-2 py-1 bg-amber-900/40 text-amber-400 border border-amber-800 rounded hover:bg-amber-900 transition-colors whitespace-nowrap"
        >
          Did not attend
        </button>
      </div>

      {pendingOutcome && (
        <AttendanceModal
          reservation={reservation}
          initialStatus={pendingOutcome}
          queryKey={queryKey}
          onClose={() => setPendingOutcome(null)}
        />
      )}
    </>
  );
}
