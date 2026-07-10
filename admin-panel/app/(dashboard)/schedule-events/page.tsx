"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import toast from "react-hot-toast";
import { getChannels } from "@/lib/api/reservations";
import {
  getEvents,
  createEvent,
  patchEvent,
  deleteEvent,
  type ScheduleEvent,
} from "@/lib/api/scheduleEvents";

function toDateString(d: Date): string {
  return d.toISOString().slice(0, 10);
}

// ── Inline form row ────────────────────────────────────────────────────────

interface FormState {
  channel_id: string;
  event_date: string;
  title: string;
  sort_order: number;
  is_active: boolean;
}

function blankForm(): FormState {
  return {
    channel_id: "",
    event_date: toDateString(new Date()),
    title: "",
    sort_order: 0,
    is_active: true,
  };
}

function EventFormRow({
  initial,
  channels,
  onSave,
  onCancel,
  saving,
}: {
  initial: FormState;
  channels: { id: string; name: string }[];
  onSave: (f: FormState) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<FormState>({ ...initial });

  return (
    <tr className="bg-indigo-900/20 border-b border-gray-700">
      <td className="px-3 py-2">
        <input
          type="date"
          value={form.event_date}
          onChange={(e) => setForm({ ...form, event_date: e.target.value })}
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-32 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </td>
      <td className="px-3 py-2">
        <select
          value={form.channel_id}
          onChange={(e) => setForm({ ...form, channel_id: e.target.value })}
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-36 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All channels</option>
          {channels.map((ch) => (
            <option key={ch.id} value={ch.id}>{ch.name}</option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2 align-top">
        <textarea
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Enter announcement message..."
          rows={3}
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-full min-w-[240px] resize-y focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="number"
          value={form.sort_order}
          onChange={(e) => setForm({ ...form, sort_order: Number(e.target.value) })}
          className="bg-gray-800 border border-gray-700 text-white text-xs rounded px-2 py-1 w-16 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </td>
      <td className="px-3 py-2">
        <input
          type="checkbox"
          checked={form.is_active}
          onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
          className="accent-indigo-500"
        />
      </td>
      <td className="px-3 py-2">
        <div className="flex gap-2">
          <button
            onClick={() => onSave(form)}
            disabled={saving || !form.title.trim()}
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

export default function ScheduleEventsPage() {
  const today = toDateString(new Date());
  const thirtyDaysLater = toDateString(new Date(Date.now() + 30 * 86400 * 1000));

  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(thirtyDaysLater);
  const [channelFilter, setChannelFilter] = useState("");
  const [showAddRow, setShowAddRow] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const queryKey = ["admin", "schedule-events", { dateFrom, dateTo, channelFilter }];

  const { data: events = [], isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      getEvents({
        date_from: dateFrom,
        date_to: dateTo,
        ...(channelFilter ? { channel_id: channelFilter } : {}),
      }),
  });

  const { data: channels = [] } = useQuery({
    queryKey: ["admin", "channels"],
    queryFn: getChannels,
    staleTime: 10 * 60 * 1000,
  });

  const activeChannels = channels.filter((c) => c.is_active);

  const createMutation = useMutation({
    mutationFn: createEvent,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      setShowAddRow(false);
      toast.success("Event created");
    },
    onError: () => toast.error("Failed to create event"),
  });

  const patchMutation = useMutation({
    mutationFn: ({ id, params }: { id: string; params: any }) => patchEvent(id, params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      setEditingId(null);
      toast.success("Event updated");
    },
    onError: () => toast.error("Failed to update event"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteEvent(id),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey });
      const prev = queryClient.getQueryData<ScheduleEvent[]>(queryKey);
      queryClient.setQueryData<ScheduleEvent[]>(
        queryKey,
        (old) => (old ?? []).filter((e) => e.id !== id)
      );
      return { prev };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(queryKey, ctx.prev);
      toast.error("Failed to delete event");
    },
    onSuccess: () => toast.success("Event deleted"),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
      setConfirmDelete(null);
    },
  });

  function handleCreate(form: FormState) {
    createMutation.mutate({
      channel_id: form.channel_id || null,
      event_date: form.event_date,
      title: form.title.trim(),
      sort_order: form.sort_order,
      is_active: form.is_active,
    });
  }

  function handleEdit(ev: ScheduleEvent, form: FormState) {
    patchMutation.mutate({
      id: ev.id,
      params: {
        title: form.title.trim(),
        sort_order: form.sort_order,
        is_active: form.is_active,
      },
    });
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">Broadcast Events</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Manage custom announcements that appear in daily broadcast messages.
          </p>
        </div>
        <button
          onClick={() => { setShowAddRow(true); setEditingId(null); }}
          className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
        >
          + Add event
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span>From</span>
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          <span>to</span>
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
        <select
          value={channelFilter}
          onChange={(e) => setChannelFilter(e.target.value)}
          className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All channels</option>
          {activeChannels.map((ch) => (
            <option key={ch.id} value={ch.id}>{ch.name}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm table-fixed">
          <thead className="bg-gray-800 text-gray-500 text-xs">
            <tr>
              <th className="px-3 py-2 text-left w-28">Date</th>
              <th className="px-3 py-2 text-left w-36">Channel</th>
              <th className="px-3 py-2 text-left">Message</th>
              <th className="px-3 py-2 text-left w-16">Order</th>
              <th className="px-3 py-2 text-left w-16">Active</th>
              <th className="px-3 py-2 text-left w-32">Actions</th>
            </tr>
          </thead>
          <tbody>
            {/* Add row */}
            {showAddRow && (
              <EventFormRow
                initial={blankForm()}
                channels={activeChannels}
                onSave={handleCreate}
                onCancel={() => setShowAddRow(false)}
                saving={createMutation.isPending}
              />
            )}

            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-600 animate-pulse">
                  Loading…
                </td>
              </tr>
            ) : events.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-600">
                  <p>No broadcast announcements scheduled yet.</p>
                  <p className="text-xs text-gray-700 mt-1">
                    Create an event to add a custom message to a daily broadcast.
                  </p>
                </td>
              </tr>
            ) : (
              events.map((ev) => {
                if (editingId === ev.id) {
                  return (
                    <EventFormRow
                      key={ev.id}
                      initial={{
                        channel_id: ev.channel_id ?? "",
                        event_date: ev.event_date,
                        title: ev.title,
                        sort_order: ev.sort_order,
                        is_active: ev.is_active,
                      }}
                      channels={activeChannels}
                      onSave={(form) => handleEdit(ev, form)}
                      onCancel={() => setEditingId(null)}
                      saving={patchMutation.isPending}
                    />
                  );
                }

                return (
                  <tr key={ev.id} className="border-t border-gray-800 hover:bg-gray-800/30">
                    <td className="px-3 py-2 text-gray-400 text-xs">{ev.event_date}</td>
                    <td className="px-3 py-2 text-gray-300">
                      {ev.channel_name ?? (
                        <span className="text-gray-600 italic">All channels</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-white">
                      <span
                        className="block truncate whitespace-nowrap"
                        title={ev.title}
                      >
                        {ev.title}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-gray-400">{ev.sort_order}</td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() =>
                          patchMutation.mutate({
                            id: ev.id,
                            params: { is_active: !ev.is_active },
                          })
                        }
                        className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors ${
                          ev.is_active ? "bg-indigo-600" : "bg-gray-700"
                        }`}
                        title={ev.is_active ? "Active — click to deactivate" : "Inactive — click to activate"}
                      >
                        <span
                          className={`inline-block h-3 w-3 rounded-full bg-white transition-transform ${
                            ev.is_active ? "translate-x-4" : "translate-x-0.5"
                          }`}
                        />
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-2">
                        <button
                          onClick={() => { setEditingId(ev.id); setShowAddRow(false); }}
                          className="text-xs text-indigo-400 hover:text-indigo-300"
                        >
                          Edit
                        </button>
                        {confirmDelete === ev.id ? (
                          <span className="text-xs">
                            <button
                              onClick={() => deleteMutation.mutate(ev.id)}
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
                            onClick={() => setConfirmDelete(ev.id)}
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
