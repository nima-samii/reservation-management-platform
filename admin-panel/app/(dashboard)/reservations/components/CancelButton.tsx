"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { cancelReservation, type ReservationItem } from "@/lib/api/reservations";

interface Props {
  reservation: ReservationItem;
  queryKey: unknown[];
}

export function CancelButton({ reservation, queryKey }: Props) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => cancelReservation(reservation.id, reason),
    onSuccess: () => {
      queryClient.setQueryData(queryKey, (old: any) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((item: ReservationItem) =>
            item.id === reservation.id ? { ...item, status: "cancelled" } : item
          ),
        };
      });
      // Refresh table + summary counts.
      queryClient.invalidateQueries({ queryKey: ["admin", "reservations"] });
      toast.success("Reservation cancelled — user notified");
      setShowConfirm(false);
      setReason("");
    },
    onError: (err: any) => {
      const status = err?.response?.status;
      if (status === 409) {
        toast("This reservation can no longer be cancelled", { icon: "ℹ️" });
      } else if (status === 404) {
        toast.error("Reservation not found");
      } else {
        toast.error(err?.response?.data?.detail ?? "Failed to cancel reservation");
      }
      setShowConfirm(false);
    },
  });

  // Only ACTIVE reservations can be cancelled; hide the button otherwise.
  if (reservation.status !== "active") {
    return null;
  }

  return (
    <>
      <button
        onClick={() => setShowConfirm(true)}
        className="text-xs px-2 py-1 bg-red-900/50 text-red-400 border border-red-800 rounded hover:bg-red-900 transition-colors"
      >
        Cancel
      </button>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full shadow-2xl">
            <h3 className="text-base font-semibold text-white mb-2">
              Cancel this reservation?
            </h3>
            <p className="text-sm text-gray-400 mb-1">
              <span className="text-white">{reservation.user.full_name}</span> ·{" "}
              {reservation.slot.slot_time_local} · {reservation.channel.name}
            </p>
            <p className="text-sm text-gray-400 mb-4">
              The user will be notified that their reservation was cancelled by
              the support team. Their score is not affected.
            </p>

            <label className="block text-xs text-gray-500 mb-1">
              Reason (optional)
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={256}
              rows={3}
              placeholder="Shown to the user if provided…"
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 mb-5 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-red-500 resize-none"
            />

            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowConfirm(false)}
                disabled={mutation.isPending}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Close
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {mutation.isPending ? "Cancelling…" : "Confirm Cancel"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
