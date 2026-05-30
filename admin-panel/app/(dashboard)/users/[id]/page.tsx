"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import toast from "react-hot-toast";
import { getUser, patchUser, type UserDetail } from "@/lib/api/users";
import { ScoreAdjustForm } from "../components/ScoreAdjustForm";
import { ScoreHistory } from "../components/ScoreHistory";
import { SendMessageForm } from "../components/SendMessageForm";
import { UserEditForm } from "../components/UserEditForm";

function CopyIdButton({ telegramId }: { telegramId: number }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(String(telegramId)).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={handleCopy}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-gray-800 text-gray-300 border border-gray-700 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
      >
        <span>{copied ? "✅" : "📋"}</span>
        <span>{copied ? "Copied!" : "Copy Telegram ID"}</span>
        <span className="font-mono text-gray-500 text-xs">{telegramId}</span>
      </button>
      <span className="text-xs text-gray-600">
        No username — forward a message in Telegram and search by this ID.
      </span>
    </div>
  );
}

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(" ")
    .slice(0, 2)
    .map((w) => (w[0] ?? "").toUpperCase())
    .join("");
  return (
    <div className="w-14 h-14 rounded-full bg-indigo-600 flex items-center justify-center text-white text-lg font-bold flex-shrink-0 select-none">
      {initials}
    </div>
  );
}

function Field({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean | null;
}) {
  const valueClass =
    positive === true
      ? "text-green-400"
      : positive === false
      ? "text-red-400"
      : "text-gray-200";
  return (
    <div>
      <dt className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</dt>
      <dd className={`text-sm ${valueClass}`}>{value}</dd>
    </div>
  );
}

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [isEditing, setIsEditing] = useState(false);
  const [showBanConfirm, setShowBanConfirm] = useState(false);

  const { data: user, isLoading, isError } = useQuery({
    queryKey: ["admin", "user", id],
    queryFn: () => getUser(id),
  });

  const banMutation = useMutation({
    mutationFn: (ban: boolean) => patchUser(id, { is_banned: ban }),
    onSuccess: (updated) => {
      queryClient.setQueryData(
        ["admin", "user", id],
        (old: UserDetail | undefined) => (old ? { ...old, is_banned: updated.is_banned } : old)
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(updated.is_banned ? "User banned" : "User unbanned");
      setShowBanConfirm(false);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail ?? "Action failed");
      setShowBanConfirm(false);
    },
  });

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-6 animate-pulse">
        <div className="h-5 bg-gray-800 rounded w-48" />
        <div className="h-56 bg-gray-800 rounded-xl" />
        <div className="h-48 bg-gray-800 rounded-xl" />
      </div>
    );
  }

  if (isError || !user) {
    return (
      <div className="text-center py-20">
        <div className="text-4xl mb-3">❌</div>
        <div className="text-red-400">User not found</div>
        <Link href="/users" className="text-indigo-400 text-sm mt-4 inline-block hover:text-indigo-300">
          ← Back to users
        </Link>
      </div>
    );
  }

  const scoreSign = user.participation_score > 0 ? "+" : "";

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-400 flex items-center gap-2">
        <Link href="/users" className="hover:text-white transition-colors">
          Users
        </Link>
        <span>›</span>
        <span className="text-white">{user.full_name}</span>
      </nav>

      {/* Ban warning banner */}
      {user.is_banned && (
        <div className="bg-red-950 border border-red-800 text-red-300 px-4 py-3 rounded-lg flex items-center gap-3">
          <span className="text-xl flex-shrink-0">⛔</span>
          <span className="text-sm">
            This user is <strong>banned</strong> and cannot use the bot.
          </span>
        </div>
      )}

      {/* Profile card */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            <Avatar name={user.full_name} />
            <div>
              <h2 className="text-xl font-semibold text-white">{user.full_name}</h2>
              <p className="text-gray-400 text-sm mt-0.5">
                #{user.public_user_code}
                {user.username && <span> · @{user.username}</span>}
              </p>
            </div>
          </div>

          <div className="flex gap-2 flex-wrap justify-end">
            {!isEditing && (
              <button
                onClick={() => setIsEditing(true)}
                className="px-3 py-1.5 text-sm bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 hover:text-white transition-colors"
              >
                Edit
              </button>
            )}
            <button
              onClick={() => setShowBanConfirm(true)}
              className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                user.is_banned
                  ? "bg-green-900 text-green-300 hover:bg-green-800"
                  : "bg-red-900 text-red-300 hover:bg-red-800"
              }`}
            >
              {user.is_banned ? "Unban" : "Ban"}
            </button>
          </div>
        </div>

        {isEditing ? (
          <UserEditForm
            user={user}
            onCancel={() => setIsEditing(false)}
            onSaved={(updated) => {
              queryClient.setQueryData(
                ["admin", "user", id],
                (old: UserDetail | undefined) => (old ? { ...old, ...updated } : old)
              );
              queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
              setIsEditing(false);
            }}
          />
        ) : (
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-4 text-sm">
            <Field label="Full name" value={user.full_name} />
            <Field label="Telegram ID" value={String(user.telegram_id)} />
            <Field label="Public code" value={`#${user.public_user_code}`} />
            <Field
              label="Gender"
              value={
                user.gender === "male"
                  ? "Male"
                  : user.gender === "female"
                  ? "Female"
                  : user.gender === "not_say"
                  ? "Prefer not to say"
                  : "—"
              }
            />
            <Field
              label="Country"
              value={
                user.country
                  ? `${user.country.flag_emoji ?? ""} ${user.country.name}`.trim()
                  : "—"
              }
            />
            <Field
              label="Score"
              value={`${scoreSign}${user.participation_score}`}
              positive={
                user.participation_score > 0
                  ? true
                  : user.participation_score < 0
                  ? false
                  : null
              }
            />
            <Field
              label="Status"
              value={user.is_banned ? "Banned" : user.is_active ? "Active" : "Inactive"}
            />
            <Field
              label="Joined"
              value={new Date(user.created_at).toLocaleString()}
            />
          </dl>
        )}

        {!isEditing && (
          <div className="mt-5 pt-4 border-t border-gray-800 flex flex-wrap items-center gap-3">
            {user.username ? (
              <a
                href={`https://t.me/${user.username}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-sky-900/50 text-sky-300 border border-sky-800 rounded-lg hover:bg-sky-900 hover:text-sky-200 transition-colors"
              >
                <span>✈️</span>
                <span>Message on Telegram</span>
                <span className="text-sky-500 text-xs">→</span>
              </a>
            ) : (
              <CopyIdButton telegramId={user.telegram_id} />
            )}
          </div>
        )}
      </section>

      {/* Score management */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-base font-semibold text-white mb-4">Score Management</h3>
        <div className="mb-5">
          <div
            className={`text-4xl font-bold tabular-nums ${
              user.participation_score > 0
                ? "text-green-400"
                : user.participation_score < 0
                ? "text-red-400"
                : "text-gray-300"
            }`}
          >
            {scoreSign}{user.participation_score}
          </div>
          <p className="text-xs text-gray-500 mt-1">Current participation score</p>
        </div>
        <ScoreAdjustForm
          userId={id}
          onSuccess={(newScore) => {
            queryClient.setQueryData(
              ["admin", "user", id],
              (old: UserDetail | undefined) =>
                old ? { ...old, participation_score: newScore } : old
            );
            queryClient.invalidateQueries({ queryKey: ["admin", "score-history", id] });
            queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
          }}
        />
      </section>

      {/* Score history */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-base font-semibold text-white mb-4">Score History</h3>
        <ScoreHistory userId={id} />
      </section>

      {/* Send message */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-base font-semibold text-white mb-4">Send Message to User</h3>
        <SendMessageForm
          userId={id}
          userName={user.full_name}
          telegramId={user.telegram_id}
        />
      </section>

      {/* Ban confirmation dialog */}
      {showBanConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-sm w-full shadow-2xl">
            <h3 className="text-lg font-semibold text-white mb-2">
              {user.is_banned ? "Unban this user?" : "Ban this user?"}
            </h3>
            <p className="text-gray-400 text-sm mb-6">
              {user.is_banned
                ? "The user will be able to interact with the bot again."
                : "The user will not be able to use the bot."}
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowBanConfirm(false)}
                disabled={banMutation.isPending}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => banMutation.mutate(!user.is_banned)}
                disabled={banMutation.isPending}
                className={`px-4 py-2 text-sm rounded-lg disabled:opacity-50 transition-colors ${
                  user.is_banned
                    ? "bg-green-600 text-white hover:bg-green-700"
                    : "bg-red-600 text-white hover:bg-red-700"
                }`}
              >
                {banMutation.isPending
                  ? "…"
                  : user.is_banned
                  ? "Yes, unban"
                  : "Yes, ban"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
