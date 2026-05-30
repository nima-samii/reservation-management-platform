"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { sendMessage } from "@/lib/api/users";

interface Props {
  userId: string;
  userName: string;
  telegramId: number;
}

export function SendMessageForm({ userId, userName, telegramId }: Props) {
  const [text, setText] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  const trimmed = text.trim();

  const mutation = useMutation({
    mutationFn: () => sendMessage(userId, trimmed),
    onSuccess: () => {
      toast.success("Message sent successfully");
      setText("");
      setShowConfirm(false);
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail ?? "Failed to send message";
      toast.error(detail);
      setShowConfirm(false);
    },
  });

  return (
    <>
      <div className="space-y-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder="Type your message here…"
          className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
        />
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-600">
            To: <span className="text-gray-400">{userName}</span>
            <span className="ml-2 font-mono text-gray-600">{telegramId}</span>
          </span>
          <button
            onClick={() => setShowConfirm(true)}
            disabled={!trimmed}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Send Message
          </button>
        </div>
      </div>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-md w-full shadow-2xl space-y-4">
            <h3 className="text-lg font-semibold text-white">Confirm Send</h3>

            <div className="space-y-1 text-sm">
              <div className="flex gap-2">
                <span className="text-gray-500 w-20 flex-shrink-0">To:</span>
                <span className="text-gray-200">{userName}</span>
              </div>
              <div className="flex gap-2">
                <span className="text-gray-500 w-20 flex-shrink-0">Telegram ID:</span>
                <span className="font-mono text-gray-300">{telegramId}</span>
              </div>
            </div>

            <div className="bg-gray-800 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-200 whitespace-pre-wrap max-h-40 overflow-auto">
              {trimmed}
            </div>

            <p className="text-sm text-gray-400">
              Are you sure you want to send this message?
            </p>

            <div className="flex gap-3 justify-end pt-1">
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
                {mutation.isPending ? "Sending…" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
