"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { markNoShow, type ReservationItem } from "@/lib/api/reservations";

interface Props {
  reservation: ReservationItem;
  queryKey: unknown[];
}

export function NoShowButton({ reservation, queryKey }: Props) {
  const [showConfirm, setShowConfirm] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => markNoShow(reservation.id),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKey, (old: any) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((item: ReservationItem) =>
            item.id === reservation.id
              ? {
                  ...item,
                  no_show_applied: true,
                  user: { ...item.user, participation_score: data.new_score },
                }
              : item
          ),
        };
      });
      toast.success("No-show applied — score updated");
      setShowConfirm(false);
    },
    onError: (err: any) => {
      const status = err?.response?.status;
      if (status === 409) {
        toast("Already applied", { icon: "ℹ️" });
      } else {
        toast.error(err?.response?.data?.detail ?? "Failed to apply no-show");
      }
      setShowConfirm(false);
    },
  });

  if (reservation.no_show_applied) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 text-xs rounded bg-red-950 text-red-400 border border-red-900">
        Applied
      </span>
    );
  }

  if (reservation.status !== "completed") {
    return null;
  }

  return (
    <>
      <button
        onClick={() => setShowConfirm(true)}
        className="text-xs px-2 py-1 bg-orange-900/50 text-orange-400 border border-orange-800 rounded hover:bg-orange-900 transition-colors"
      >
        Mark no-show
      </button>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full shadow-2xl">
            <h3 className="text-base font-semibold text-white mb-2">
              Mark as no-show?
            </h3>
            <p className="text-sm text-gray-400 mb-1">
              <span className="text-white">{reservation.user.full_name}</span>
            </p>
            <p className="text-sm text-gray-400 mb-5">
              This will deduct 1 point from their score (current:{" "}
              <span className="text-white">{reservation.user.participation_score}</span>).
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowConfirm(false)}
                disabled={mutation.isPending}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
                className="px-4 py-2 text-sm bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-colors"
              >
                {mutation.isPending ? "Applying…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
