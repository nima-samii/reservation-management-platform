"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { adjustScore } from "@/lib/api/users";

interface Props {
  userId: string;
  onSuccess: (newScore: number) => void;
}

export function ScoreAdjustForm({ userId, onSuccess }: Props) {
  const [delta, setDelta] = useState<number | "">(1);
  const [reason, setReason] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  const mutation = useMutation({
    mutationFn: () =>
      adjustScore(userId, { delta: Number(delta), reason: reason.trim() }),
    onSuccess: (data) => {
      const sign = data.new_score > 0 ? "+" : "";
      toast.success(`Score adjusted → ${sign}${data.new_score}`);
      onSuccess(data.new_score);
      setDelta(1);
      setReason("");
      setShowConfirm(false);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Failed to adjust score");
      setShowConfirm(false);
    },
  });

  const deltaNum = Number(delta);
  const canSubmit =
    delta !== "" &&
    deltaNum !== 0 &&
    Math.abs(deltaNum) <= 100 &&
    reason.trim().length >= 5;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setShowConfirm(true);
  }

  return (
    <>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
              Delta (−100 to +100, nonzero)
            </label>
            <input
              type="number"
              min={-100}
              max={100}
              value={delta}
              onChange={(e) =>
                setDelta(e.target.value === "" ? "" : Number(e.target.value))
              }
              className="w-28 bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div className="flex-1 min-w-48">
            <label className="block text-xs text-gray-500 uppercase tracking-wide mb-1">
              Reason (min 5 chars)
            </label>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason for adjustment…"
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={!canSubmit}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Adjust
          </button>
        </div>
        {delta !== "" && deltaNum === 0 && (
          <p className="text-xs text-red-400">Delta must not be zero.</p>
        )}
      </form>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full shadow-2xl">
            <h3 className="text-lg font-semibold text-white mb-4">Confirm Score Adjustment</h3>
            <dl className="space-y-2 text-sm mb-6">
              <div className="flex gap-2">
                <dt className="text-gray-500 w-16">Delta</dt>
                <dd className={deltaNum > 0 ? "text-green-400 font-medium" : "text-red-400 font-medium"}>
                  {deltaNum > 0 ? "+" : ""}{deltaNum}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-gray-500 w-16">Reason</dt>
                <dd className="text-gray-200 flex-1">{reason}</dd>
              </div>
            </dl>
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
                className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {mutation.isPending ? "Saving…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
