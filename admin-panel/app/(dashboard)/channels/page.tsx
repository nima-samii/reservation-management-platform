"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import toast from "react-hot-toast";
import {
  getChannels,
  createChannel,
  updateChannel,
  deleteChannel,
  moveChannel,
  type Channel,
} from "@/lib/api/channels";

function extractErrorMessage(err: unknown): string {
  const anyErr = err as { response?: { data?: { detail?: string } } };
  return anyErr?.response?.data?.detail ?? "Something went wrong";
}

// ── Inline form row (create + edit) ─────────────────────────────────────────

interface FormState {
  name: string;
  telegram_channel_id: string;
  invite_link: string;
}

function blankForm(): FormState {
  return { name: "", telegram_channel_id: "", invite_link: "" };
}

function ChannelFormRow({
  initial,
  isEdit,
  onSave,
  onCancel,
  saving,
}: {
  initial: FormState;
  isEdit: boolean;
  onSave: (f: FormState) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<FormState>({ ...initial });

  const telegramIdValid = isEdit || /^-\d+$/.test(form.telegram_channel_id.trim());
  const canSave = form.name.trim().length > 0 && telegramIdValid;

  return (
    <tr className="bg-indigo-900/20 border-b border-gray-700">
      <td className="px-3 py-2">
        <input
          type="text"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Channel name"
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-full min-w-[140px] focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="text"
          value={form.telegram_channel_id}
          disabled={isEdit}
          onChange={(e) => setForm({ ...form, telegram_channel_id: e.target.value })}
          placeholder="-1001234567890"
          title={isEdit ? "Telegram ID cannot be changed after creation" : undefined}
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-36 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="text"
          value={form.invite_link}
          onChange={(e) => setForm({ ...form, invite_link: e.target.value })}
          placeholder="https://t.me/+..."
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-full min-w-[160px] focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </td>
      <td className="px-3 py-2 text-gray-600 text-xs">—</td>
      <td className="px-3 py-2 text-gray-600 text-xs">—</td>
      <td className="px-3 py-2 text-gray-600 text-xs">—</td>
      <td className="px-3 py-2">
        <div className="flex gap-2">
          <button
            onClick={() => onSave(form)}
            disabled={saving || !canSave}
            className="px-2 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {saving ? "…" : "Save"}
          </button>
          <button
            onClick={onCancel}
            className="px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600 transition-colors"
          >
            Cancel
          </button>
        </div>
      </td>
    </tr>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function ChannelsPage() {
  const [showAddRow, setShowAddRow] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const queryKey = ["admin", "channels", "full"];

  const { data: channels = [], isLoading } = useQuery({
    queryKey,
    queryFn: getChannels,
  });

  const createMutation = useMutation({
    mutationFn: createChannel,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      setShowAddRow(false);
      toast.success("Channel created");
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, params }: { id: string; params: Parameters<typeof updateChannel>[1] }) =>
      updateChannel(id, params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      setEditingId(null);
      toast.success("Channel updated");
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteChannel(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
      toast.success("Channel deleted");
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
    onSettled: () => setConfirmDelete(null),
  });

  const moveMutation = useMutation({
    mutationFn: ({ id, direction }: { id: string; direction: "up" | "down" }) =>
      moveChannel(id, direction),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      queryClient.invalidateQueries({ queryKey: ["admin", "channels"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err)),
  });

  function handleCreate(form: FormState) {
    createMutation.mutate({
      name: form.name.trim(),
      telegram_channel_id: Number(form.telegram_channel_id.trim()),
      invite_link: form.invite_link.trim() || null,
    });
  }

  function handleEdit(ch: Channel, form: FormState) {
    updateMutation.mutate({
      id: ch.id,
      params: {
        name: form.name.trim(),
        invite_link: form.invite_link.trim() || null,
      },
    });
  }

  const sorted = [...channels].sort((a, b) => a.priority - b.priority);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Channels</h1>
        <button
          onClick={() => { setShowAddRow(true); setEditingId(null); }}
          className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
        >
          + New Channel
        </button>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-500 text-xs">
            <tr>
              <th className="px-3 py-2 text-left">Name</th>
              <th className="px-3 py-2 text-left">Telegram ID</th>
              <th className="px-3 py-2 text-left">Invite Link</th>
              <th className="px-3 py-2 text-left">Active</th>
              <th className="px-3 py-2 text-left">Created</th>
              <th className="px-3 py-2 text-left">Updated</th>
              <th className="px-3 py-2 text-left">Actions</th>
            </tr>
          </thead>
          <tbody>
            {showAddRow && (
              <ChannelFormRow
                initial={blankForm()}
                isEdit={false}
                onSave={handleCreate}
                onCancel={() => setShowAddRow(false)}
                saving={createMutation.isPending}
              />
            )}

            {isLoading ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-600 animate-pulse">
                  Loading…
                </td>
              </tr>
            ) : sorted.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-600">
                  No channels yet. Create one to start generating slots.
                </td>
              </tr>
            ) : (
              sorted.map((ch, idx) => {
                if (editingId === ch.id) {
                  return (
                    <ChannelFormRow
                      key={ch.id}
                      initial={{
                        name: ch.name,
                        telegram_channel_id: String(ch.telegram_channel_id),
                        invite_link: ch.invite_link ?? "",
                      }}
                      isEdit
                      onSave={(form) => handleEdit(ch, form)}
                      onCancel={() => setEditingId(null)}
                      saving={updateMutation.isPending}
                    />
                  );
                }

                return (
                  <tr key={ch.id} className="border-t border-gray-800 hover:bg-gray-800/30">
                    <td className="px-3 py-2 text-white">{ch.name}</td>
                    <td className="px-3 py-2 text-gray-400 font-mono text-xs">
                      {ch.telegram_channel_id}
                    </td>
                    <td className="px-3 py-2 text-gray-400 text-xs truncate max-w-[200px]">
                      {ch.invite_link ?? <span className="text-gray-600 italic">none</span>}
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() =>
                          updateMutation.mutate({
                            id: ch.id,
                            params: { is_active: !ch.is_active },
                          })
                        }
                        className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors ${
                          ch.is_active ? "bg-indigo-600" : "bg-gray-700"
                        }`}
                        title={ch.is_active ? "Active — click to disable" : "Inactive — click to enable"}
                      >
                        <span
                          className={`inline-block h-3 w-3 rounded-full bg-white transition-transform ${
                            ch.is_active ? "translate-x-4" : "translate-x-0.5"
                          }`}
                        />
                      </button>
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">
                      {new Date(ch.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-xs">
                      {new Date(ch.updated_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => moveMutation.mutate({ id: ch.id, direction: "up" })}
                          disabled={idx === 0 || moveMutation.isPending}
                          className="text-xs text-gray-400 hover:text-white disabled:opacity-30 disabled:hover:text-gray-400"
                          title="Move up"
                        >
                          ↑
                        </button>
                        <button
                          onClick={() => moveMutation.mutate({ id: ch.id, direction: "down" })}
                          disabled={idx === sorted.length - 1 || moveMutation.isPending}
                          className="text-xs text-gray-400 hover:text-white disabled:opacity-30 disabled:hover:text-gray-400"
                          title="Move down"
                        >
                          ↓
                        </button>
                        <button
                          onClick={() => { setEditingId(ch.id); setShowAddRow(false); }}
                          className="text-xs text-indigo-400 hover:text-indigo-300"
                        >
                          Edit
                        </button>
                        {confirmDelete === ch.id ? (
                          <span className="text-xs">
                            <button
                              onClick={() => deleteMutation.mutate(ch.id)}
                              className="text-red-400 hover:text-red-300 mr-1"
                            >
                              Confirm
                            </button>
                            <button
                              onClick={() => setConfirmDelete(null)}
                              className="text-gray-500 hover:text-gray-300"
                            >
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            onClick={() => setConfirmDelete(ch.id)}
                            className="text-xs text-gray-500 hover:text-red-400"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
