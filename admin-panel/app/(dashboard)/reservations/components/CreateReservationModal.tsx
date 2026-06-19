"use client";

import { useState, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";
import {
  getChannels,
  getAvailableSlots,
  createReservation,
} from "@/lib/api/reservations";
import { getUsers, type UserListItem } from "@/lib/api/users";

interface Props {
  onClose: () => void;
}

function toDateString(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function CreateReservationModal({ onClose }: Props) {
  const queryClient = useQueryClient();

  const [userSearch, setUserSearch] = useState("");
  const [debouncedUserSearch, setDebouncedUserSearch] = useState("");
  const [selectedUser, setSelectedUser] = useState<UserListItem | null>(null);
  const [channelId, setChannelId] = useState("");
  const [date, setDate] = useState(toDateString(new Date()));
  const [slotId, setSlotId] = useState("");

  // Debounce user search 350ms.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedUserSearch(userSearch), 350);
    return () => clearTimeout(t);
  }, [userSearch]);

  // Re-selecting channel/date invalidates the chosen slot.
  useEffect(() => {
    setSlotId("");
  }, [channelId, date]);

  const { data: userResults, isFetching: usersFetching } = useQuery({
    queryKey: ["admin", "users", "picker", debouncedUserSearch],
    queryFn: () => getUsers({ search: debouncedUserSearch, page_size: 8 }),
    enabled: !selectedUser && debouncedUserSearch.trim().length >= 2,
  });

  const { data: channels } = useQuery({
    queryKey: ["admin", "channels"],
    queryFn: getChannels,
    staleTime: 10 * 60 * 1000,
  });

  const {
    data: slots,
    isFetching: slotsFetching,
  } = useQuery({
    queryKey: ["admin", "available-slots", channelId, date],
    queryFn: () => getAvailableSlots(channelId, date),
    enabled: !!channelId && !!date,
  });

  const mutation = useMutation({
    mutationFn: () =>
      createReservation({ user_id: selectedUser!.id, slot_id: slotId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "reservations"] });
      toast.success("Reservation created — user notified");
      onClose();
    },
    onError: (err: any) => {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 409) {
        // Daily-limit, max-active, or slot-taken — refresh slots so picker heals.
        queryClient.invalidateQueries({
          queryKey: ["admin", "available-slots", channelId, date],
        });
        setSlotId("");
        toast.error(detail ?? "Slot unavailable or booking limit reached");
      } else if (status === 422) {
        toast.error(detail ?? "Booking not allowed (cutoff or banned user)");
      } else if (status === 404) {
        toast.error("User or slot not found");
      } else {
        toast.error(detail ?? "Failed to create reservation");
      }
    },
  });

  const canSubmit = !!selectedUser && !!slotId && !mutation.isPending;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 max-w-md w-full shadow-2xl max-h-[90vh] overflow-y-auto">
        <h3 className="text-base font-semibold text-white mb-4">
          Create Reservation
        </h3>

        {/* 1. User picker */}
        <label className="block text-xs text-gray-500 mb-1">User</label>
        {selectedUser ? (
          <div className="flex items-center justify-between bg-gray-800 border border-gray-700 rounded-md px-3 py-2 mb-4">
            <div className="text-sm">
              <div className="text-white font-medium">
                {selectedUser.full_name}
              </div>
              <div className="text-gray-400 text-xs">
                Code {selectedUser.public_user_code} · TG{" "}
                {selectedUser.telegram_id}
                {selectedUser.is_banned && (
                  <span className="ml-2 text-red-400">banned</span>
                )}
              </div>
            </div>
            <button
              onClick={() => {
                setSelectedUser(null);
                setUserSearch("");
              }}
              className="text-xs text-gray-400 hover:text-white"
            >
              Change
            </button>
          </div>
        ) : (
          <div className="mb-4">
            <input
              type="search"
              value={userSearch}
              onChange={(e) => setUserSearch(e.target.value)}
              placeholder="Search name, username or code…"
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
            {debouncedUserSearch.trim().length >= 2 && (
              <div className="mt-1 border border-gray-800 rounded-md divide-y divide-gray-800 max-h-44 overflow-y-auto">
                {usersFetching && (
                  <div className="px-3 py-2 text-xs text-gray-500">Searching…</div>
                )}
                {!usersFetching && userResults?.items.length === 0 && (
                  <div className="px-3 py-2 text-xs text-gray-500">
                    No users found
                  </div>
                )}
                {userResults?.items.map((u) => (
                  <button
                    key={u.id}
                    onClick={() => setSelectedUser(u)}
                    className="w-full text-left px-3 py-2 hover:bg-gray-800 transition-colors"
                  >
                    <div className="text-sm text-white">{u.full_name}</div>
                    <div className="text-xs text-gray-500">
                      Code {u.public_user_code} · TG {u.telegram_id}
                      {u.is_banned && (
                        <span className="ml-2 text-red-400">banned</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 2. Channel picker */}
        <label className="block text-xs text-gray-500 mb-1">Channel</label>
        <select
          value={channelId}
          onChange={(e) => setChannelId(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 text-sm text-white rounded-md px-3 py-2 mb-4 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">Select a channel…</option>
          {channels?.map((ch) => (
            <option key={ch.id} value={ch.id}>
              {ch.name}
            </option>
          ))}
        </select>

        {/* 3. Date picker */}
        <label className="block text-xs text-gray-500 mb-1">Date</label>
        <input
          type="date"
          value={date}
          min={toDateString(new Date())}
          onChange={(e) => setDate(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 mb-4 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />

        {/* 4. Slot picker */}
        <label className="block text-xs text-gray-500 mb-1">Slot</label>
        {!channelId ? (
          <p className="text-xs text-gray-600 mb-5">
            Select a channel and date to load slots.
          </p>
        ) : slotsFetching ? (
          <p className="text-xs text-gray-500 mb-5">Loading slots…</p>
        ) : slots && slots.length > 0 ? (
          <div className="grid grid-cols-4 gap-2 mb-5">
            {slots.map((s) => (
              <button
                key={s.id}
                onClick={() => setSlotId(s.id)}
                className={`px-2 py-1.5 text-xs rounded-md border transition-colors ${
                  slotId === s.id
                    ? "bg-indigo-600 border-indigo-500 text-white"
                    : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
                }`}
              >
                {s.slot_time_local}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-600 mb-5">
            No open slots for this channel and date.
          </p>
        )}

        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            disabled={mutation.isPending}
            className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={!canSubmit}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {mutation.isPending ? "Creating…" : "Create Reservation"}
          </button>
        </div>
      </div>
    </div>
  );
}
