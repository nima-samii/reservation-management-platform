"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  recordAttendance,
  ATTENDANCE_REASON_MAX,
  ATTENDANCE_SCORE_LIMIT,
  type AttendanceStatus,
  type ReservationItem,
} from "@/lib/api/reservations";

interface Props {
  reservation: ReservationItem;
  /** Which button opened the modal. Still switchable inside — a misclick
   *  should not cost a round trip through Cancel. */
  initialStatus: AttendanceStatus;
  /** The query whose cache holds this reservation: the paginated list on the
   *  index page, the single detail object on the detail page. Both shapes are
   *  handled below. */
  queryKey: unknown[];
  onClose: () => void;
}

const OUTCOMES: { value: AttendanceStatus; label: string; hint: string }[] = [
  { value: "attended", label: "Attended", hint: "took part in the session" },
  { value: "absent", label: "Did not attend", hint: "did not take part" },
];

export function AttendanceModal({
  reservation,
  initialStatus,
  queryKey,
  onClose,
}: Props) {
  const [status, setStatus] = useState<AttendanceStatus>(initialStatus);
  // Kept as a string so "-" and "" are typable on the way to "-5". Parsed once
  // on submit; a number-typed state would fight the user mid-keystroke.
  const [scoreText, setScoreText] = useState("0");
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();

  const score = Number(scoreText);
  const scoreIsValid =
    scoreText.trim() !== "" &&
    Number.isInteger(score) &&
    Math.abs(score) <= ATTENDANCE_SCORE_LIMIT;
  const reasonIsValid =
    reason.trim().length > 0 && reason.trim().length <= ATTENDANCE_REASON_MAX;

  const mutation = useMutation({
    mutationFn: () =>
      recordAttendance(reservation.id, {
        attendance_status: status,
        score_delta: score,
        reason: reason.trim(),
      }),
    onSuccess: (data) => {
      const patch = (item: ReservationItem): ReservationItem => ({
        ...item,
        attendance_status: data.attendance_status,
        attendance_score_delta: data.score_delta,
        attendance_reason: data.reason,
        attendance_marked_by: data.marked_by,
        attendance_marked_at: data.marked_at,
        user: { ...item.user, participation_score: data.new_score },
      });

      queryClient.setQueryData(queryKey, (old: any) => {
        if (!old) return old;
        // The list page caches a page of items; the detail page caches one.
        if (Array.isArray(old.items)) {
          return {
            ...old,
            items: old.items.map((item: ReservationItem) =>
              item.id === reservation.id ? patch(item) : item
            ),
          };
        }
        return old.id === reservation.id ? patch(old) : old;
      });

      // The decision is a new timeline event, and the summary counts moved
      // (one fewer awaiting a decision). Neither is derivable from the
      // response, so they are refetched rather than guessed.
      queryClient.invalidateQueries({
        queryKey: ["admin", "reservation-timeline", reservation.id],
      });
      queryClient.invalidateQueries({ queryKey: ["admin", "reservations"] });

      toast.success(
        data.score_delta === 0
          ? "Recorded — no score change"
          : `Recorded — score ${data.score_delta > 0 ? "+" : ""}${data.score_delta}`
      );
      onClose();
    },
    onError: (err: any) => {
      const httpStatus = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (httpStatus === 409) {
        // The three conflicts carry distinct messages — not completed yet,
        // already decided, already scored by the retired penalty — and an
        // admin needs to know which, because only one of them is "wait".
        toast(typeof detail === "string" ? detail : "Already recorded", {
          icon: "ℹ️",
          duration: 6000,
        });
        queryClient.invalidateQueries({ queryKey: ["admin", "reservations"] });
        onClose();
        return;
      }
      toast.error(
        typeof detail === "string" ? detail : "Failed to record attendance"
      );
    },
  });

  const canSubmit = scoreIsValid && reasonIsValid && !mutation.isPending;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-md w-full shadow-2xl">
        <h3 className="text-base font-semibold text-white mb-1">
          Record attendance
        </h3>
        <p className="text-sm text-gray-400 mb-5">
          <span className="text-white">{reservation.user.full_name}</span> ·{" "}
          {reservation.slot.slot_time_local} · {reservation.channel.name}
        </p>

        {/* Outcome — independent of the score below */}
        <div className="mb-4">
          <label className="block text-xs text-gray-500 uppercase tracking-wide mb-2">
            Outcome
          </label>
          <div className="flex rounded-lg overflow-hidden border border-gray-700 text-sm">
            {OUTCOMES.map((o) => (
              <button
                key={o.value}
                type="button"
                onClick={() => setStatus(o.value)}
                className={`flex-1 px-3 py-2 transition-colors ${
                  status === o.value
                    ? "bg-indigo-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:text-white"
                }`}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        {/* Score — any sign, deliberately not derived from the outcome */}
        <div className="mb-4">
          <label
            htmlFor="attendance-score"
            className="block text-xs text-gray-500 uppercase tracking-wide mb-2"
          >
            Score
          </label>
          <input
            id="attendance-score"
            type="number"
            inputMode="numeric"
            value={scoreText}
            min={-ATTENDANCE_SCORE_LIMIT}
            max={ATTENDANCE_SCORE_LIMIT}
            step={1}
            onChange={(e) => setScoreText(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 tabular-nums focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <p className="mt-1.5 text-xs text-gray-500">
            Positive, zero or negative — the outcome above does not decide it.
            An absence can still earn points, and an attended session can be
            worth none.
          </p>
          {!scoreIsValid && scoreText.trim() !== "" && (
            <p className="mt-1 text-xs text-red-400">
              Whole number between -{ATTENDANCE_SCORE_LIMIT} and{" "}
              {ATTENDANCE_SCORE_LIMIT}.
            </p>
          )}
        </div>

        {/* Explanation — quoted back to the user, so required */}
        <div className="mb-2">
          <label
            htmlFor="attendance-reason"
            className="block text-xs text-gray-500 uppercase tracking-wide mb-2"
          >
            Explanation <span className="text-red-400">*</span>
          </label>
          <textarea
            id="attendance-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            maxLength={ATTENDANCE_REASON_MAX}
            placeholder="Why this outcome and this score…"
            className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 placeholder-gray-600 resize-none focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <div className="flex items-center justify-between mt-1">
            <p className="text-xs text-gray-500">
              Sent to the user with the result.
            </p>
            <span className="text-xs text-gray-600 tabular-nums">
              {reason.trim().length}/{ATTENDANCE_REASON_MAX}
            </span>
          </div>
        </div>

        <p className="text-xs text-amber-500/80 mb-5">
          One decision per reservation — it cannot be edited afterwards. A
          correction goes through a score adjustment on the user.
        </p>

        <div className="flex gap-3 justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={mutation.isPending}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {mutation.isPending ? "Recording…" : "Record"}
          </button>
        </div>
      </div>
    </div>
  );
}
