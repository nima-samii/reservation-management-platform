"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import {
  getSettings,
  patchSettings,
  getSettingsHistory,
  type AllSettings,
  type ReservationRules,
  type SlotSchedule,
  type Notifications,
  type BroadcastSettings,
} from "@/lib/api/settings";

// ── Generic field components ───────────────────────────────────────────────

function NumberField({
  label,
  value,
  min,
  max,
  step,
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
      {hint && <p className="text-xs text-gray-600 mt-0.5">{hint}</p>}
    </div>
  );
}

function TextField({
  label,
  value,
  hint,
  onChange,
}: {
  label: string;
  value: string;
  hint?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-xs text-gray-400 mb-1">{label}</label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
      />
      {hint && <p className="text-xs text-gray-600 mt-0.5">{hint}</p>}
    </div>
  );
}

function ToggleField({
  label,
  value,
  hint,
  onChange,
}: {
  label: string;
  value: boolean;
  hint?: string;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <span className="text-sm text-gray-300">{label}</span>
        {hint && <p className="text-xs text-gray-600 mt-0.5">{hint}</p>}
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
          value ? "bg-indigo-600" : "bg-gray-700"
        }`}
      >
        <span
          className={`inline-block h-3 w-3 rounded-full bg-white transition-transform ${
            value ? "translate-x-5" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  );
}

// ── Section wrapper ────────────────────────────────────────────────────────

function Section({
  title,
  dirty,
  saving,
  onSave,
  children,
}: {
  title: string;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-5 py-4 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-sm font-medium text-white flex items-center gap-2">
          {title}
          {dirty && (
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400" title="Unsaved changes" />
          )}
        </span>
        <span className="text-gray-500 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">{children}</div>
          <button
            onClick={onSave}
            disabled={saving || !dirty}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {saving ? "Saving…" : "Save changes"}
          </button>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: getSettings,
  });

  const { data: history } = useQuery({
    queryKey: ["admin", "settings", "history"],
    queryFn: getSettingsHistory,
  });

  // Local state per section
  const [res, setRes] = useState<ReservationRules | null>(null);
  const [slot, setSlot] = useState<SlotSchedule | null>(null);
  const [notif, setNotif] = useState<Notifications | null>(null);
  const [bcast, setBcast] = useState<BroadcastSettings | null>(null);

  // Dirty flags
  const [resDirty, setResDirty] = useState(false);
  const [slotDirty, setSlotDirty] = useState(false);
  const [notifDirty, setNotifDirty] = useState(false);
  const [bcastDirty, setBcastDirty] = useState(false);

  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    if (settings) {
      setRes({ ...settings.reservation_rules });
      setSlot({ ...settings.slot_schedule });
      setNotif({ ...settings.notifications });
      setBcast({ ...settings.broadcast });
      setResDirty(false);
      setSlotDirty(false);
      setNotifDirty(false);
      setBcastDirty(false);
    }
  }, [settings]);

  // Warn on navigate away with unsaved changes
  useEffect(() => {
    const anyDirty = resDirty || slotDirty || notifDirty || bcastDirty;
    const handler = (e: BeforeUnloadEvent) => {
      if (anyDirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [resDirty, slotDirty, notifDirty, bcastDirty]);

  const mutation = useMutation({
    mutationFn: patchSettings,
    onSuccess: (updated) => {
      queryClient.setQueryData(["admin", "settings"], updated);
      queryClient.invalidateQueries({ queryKey: ["admin", "settings", "history"] });
      toast.success("Settings saved");
    },
    onError: () => toast.error("Failed to save settings"),
  });

  if (isLoading || !res || !slot || !notif || !bcast) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-gray-500 animate-pulse">Loading settings…</span>
      </div>
    );
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <h1 className="text-xl font-semibold text-white">Settings</h1>

      <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-4 py-3 text-sm text-amber-300">
        Changes to slot schedule or hours take effect on the next scheduler run. Existing
        reservations are not affected.
      </div>

      {/* Reservation rules */}
      <Section
        title="Reservation rules"
        dirty={resDirty}
        saving={mutation.isPending}
        onSave={() => {
          mutation.mutate({ reservation_rules: res });
          setResDirty(false);
        }}
      >
        <NumberField
          label="Max active reservations"
          value={res.max_active_reservations}
          min={1} max={50}
          hint="Per user limit"
          onChange={(v) => { setRes({ ...res, max_active_reservations: v }); setResDirty(true); }}
        />
        <NumberField
          label="Max days ahead"
          value={res.max_reservation_days_ahead}
          min={1} max={60}
          onChange={(v) => { setRes({ ...res, max_reservation_days_ahead: v }); setResDirty(true); }}
        />
        <NumberField
          label="Channel capacity threshold"
          value={res.channel_capacity_threshold}
          min={0.1} max={1.0} step={0.05}
          hint="0.0–1.0 (e.g. 0.7 = 70%)"
          onChange={(v) => { setRes({ ...res, channel_capacity_threshold: v }); setResDirty(true); }}
        />
        <NumberField
          label="Same-day cutoff hour (0–23)"
          value={res.same_day_cutoff_hour}
          min={0} max={23}
          hint="No new bookings after this hour"
          onChange={(v) => { setRes({ ...res, same_day_cutoff_hour: v }); setResDirty(true); }}
        />
        <NumberField
          label="Same-day cancel cutoff hour (0–23)"
          value={res.same_day_cancel_cutoff_hour}
          min={0} max={23}
          hint="No cancellations after this hour"
          onChange={(v) => { setRes({ ...res, same_day_cancel_cutoff_hour: v }); setResDirty(true); }}
        />
      </Section>

      {/* Slot schedule */}
      <Section
        title="Slot schedule"
        dirty={slotDirty}
        saving={mutation.isPending}
        onSave={() => {
          mutation.mutate({ slot_schedule: slot });
          setSlotDirty(false);
        }}
      >
        <NumberField
          label="Slot start hour (0–23)"
          value={slot.slot_start_hour}
          min={0} max={23}
          onChange={(v) => { setSlot({ ...slot, slot_start_hour: v }); setSlotDirty(true); }}
        />
        <NumberField
          label="Slot end hour (0–24)"
          value={slot.slot_end_hour}
          min={0} max={24}
          hint="24 = midnight"
          onChange={(v) => { setSlot({ ...slot, slot_end_hour: v }); setSlotDirty(true); }}
        />
        <NumberField
          label="Slot duration (minutes)"
          value={slot.slot_duration_minutes}
          min={5} max={120}
          onChange={(v) => { setSlot({ ...slot, slot_duration_minutes: v }); setSlotDirty(true); }}
        />
        <div className="sm:col-span-2">
          <ToggleField
            label="Enable final midnight slot"
            value={slot.enable_final_midnight_slot}
            onChange={(v) => { setSlot({ ...slot, enable_final_midnight_slot: v }); setSlotDirty(true); }}
          />
        </div>
        <TextField
          label="Final slot time (HH:MM)"
          value={slot.final_slot_time}
          hint="Only used when final midnight slot is enabled"
          onChange={(v) => { setSlot({ ...slot, final_slot_time: v }); setSlotDirty(true); }}
        />
      </Section>

      {/* Notifications */}
      <Section
        title="Notifications & reminders"
        dirty={notifDirty}
        saving={mutation.isPending}
        onSave={() => {
          mutation.mutate({ notifications: notif });
          setNotifDirty(false);
        }}
      >
        <NumberField
          label="Same-day reminder hour (0–23)"
          value={notif.same_day_reminder_hour}
          min={0} max={23}
          onChange={(v) => { setNotif({ ...notif, same_day_reminder_hour: v }); setNotifDirty(true); }}
        />
        <NumberField
          label="Pre-session reminder (minutes)"
          value={notif.pre_session_reminder_minutes}
          min={5} max={180}
          hint="Minutes before session start"
          onChange={(v) => { setNotif({ ...notif, pre_session_reminder_minutes: v }); setNotifDirty(true); }}
        />
      </Section>

      {/* Daily broadcast */}
      <Section
        title="Daily broadcast"
        dirty={bcastDirty}
        saving={mutation.isPending}
        onSave={() => {
          mutation.mutate({ broadcast: bcast });
          setBcastDirty(false);
        }}
      >
        <NumberField
          label="Broadcast hour (0–23)"
          value={bcast.daily_broadcast_hour}
          min={0} max={23}
          onChange={(v) => { setBcast({ ...bcast, daily_broadcast_hour: v }); setBcastDirty(true); }}
        />
        <div className="sm:col-span-2 space-y-3">
          <ToggleField
            label="Auto-pin broadcast message"
            value={bcast.enable_broadcast_auto_pin}
            onChange={(v) => { setBcast({ ...bcast, enable_broadcast_auto_pin: v }); setBcastDirty(true); }}
          />
          <ToggleField
            label="Delete previous broadcast"
            value={bcast.delete_previous_broadcast}
            onChange={(v) => { setBcast({ ...bcast, delete_previous_broadcast: v }); setBcastDirty(true); }}
          />
        </div>
      </Section>

      {/* Change history */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <button
          className="w-full flex items-center justify-between px-5 py-4 text-left"
          onClick={() => setShowHistory((s) => !s)}
        >
          <span className="text-sm font-medium text-white">Change history</span>
          <span className="text-gray-500 text-xs">{showHistory ? "▲ Hide" : "▼ Show"}</span>
        </button>
        {showHistory && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-gray-400">
              <thead className="bg-gray-800 text-gray-500">
                <tr>
                  <th className="px-4 py-2 text-left">When</th>
                  <th className="px-4 py-2 text-left">Field</th>
                  <th className="px-4 py-2 text-left">Old value</th>
                  <th className="px-4 py-2 text-left">New value</th>
                  <th className="px-4 py-2 text-left">By</th>
                </tr>
              </thead>
              <tbody>
                {(history ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-4 text-center text-gray-600">
                      No changes yet
                    </td>
                  </tr>
                ) : (
                  (history ?? []).map((h, i) => (
                    <tr key={i} className="border-t border-gray-800">
                      <td className="px-4 py-2 whitespace-nowrap">
                        {new Date(h.changed_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 font-mono">{h.field}</td>
                      <td className="px-4 py-2 text-gray-600">{h.old_value}</td>
                      <td className="px-4 py-2 text-green-400">{h.new_value}</td>
                      <td className="px-4 py-2">{h.changed_by}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
