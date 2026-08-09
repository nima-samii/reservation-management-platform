"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import {
  getSettingsMetadata,
  getSettings,
  patchSettings,
  getSettingsHistory,
  getMembershipChannels,
  putMembershipChannels,
  type SettingsValues,
  type SettingFieldMeta,
  type SettingCategoryMeta,
  type MembershipChannel,
  type RestartBehavior,
} from "@/lib/api/settings";
import {
  validateFieldValue,
  validateMembershipChannelId,
  validateMembershipChannelUrl,
} from "@/lib/settings-validation";

function extractErrorMessage(err: unknown): string | undefined {
  if (err && typeof err === "object" && "response" in err) {
    const resp = (err as { response?: { data?: { detail?: string } } }).response;
    return resp?.data?.detail;
  }
  return undefined;
}

// ── Restart badge ───────────────────────────────────────────────────────────
// The one place that's a hover-only tooltip (per the audit's recommendation) —
// field descriptions themselves stay permanently visible as inline hint text.

const RESTART_BADGE: Record<RestartBehavior, { label: string; className: string; hint: string }> = {
  live: {
    label: "Live",
    className: "bg-green-900/40 text-green-400 border-green-700/40",
    hint: "Applies immediately — no restart needed.",
  },
  cache_refresh: {
    label: "Cache Refresh",
    className: "bg-blue-900/40 text-blue-400 border-blue-700/40",
    hint: "Applies to the next cached entry, not retroactively.",
  },
  scheduler_restart: {
    label: "Scheduler Restart",
    className: "bg-amber-900/40 text-amber-400 border-amber-700/40",
    hint: "This job's schedule is fixed at process startup — the app must be restarted for this change to take effect.",
  },
  restart_required: {
    label: "Restart Required",
    className: "bg-red-900/40 text-red-400 border-red-700/40",
    hint: "Requires a full application restart to take effect.",
  },
};

function RestartBadge({ behavior }: { behavior: RestartBehavior }) {
  const b = RESTART_BADGE[behavior];
  return (
    <span
      className={`group relative inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-medium cursor-help shrink-0 ${b.className}`}
    >
      {b.label}
      <span className="pointer-events-none absolute z-10 left-1/2 -translate-x-1/2 bottom-full mb-1 w-48 rounded-md bg-gray-950 border border-gray-700 px-2 py-1.5 text-[11px] text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity">
        {b.hint}
      </span>
    </span>
  );
}

// ── Info tooltip ─────────────────────────────────────────────────────────────

function InfoTooltip({ meta }: { meta: SettingFieldMeta }) {
  return (
    <span className="group relative inline-flex items-center text-gray-500 cursor-help shrink-0">
      ⓘ
      <span className="pointer-events-none absolute z-10 left-0 bottom-full mb-1 w-64 rounded-md bg-gray-950 border border-gray-700 px-3 py-2 text-xs text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity space-y-1">
        <p>{meta.description}</p>
        <p className="text-gray-500">
          Example: <span className="text-gray-400">{String(meta.example)}</span>
        </p>
        {(meta.min !== null || meta.max !== null) && (
          <p className="text-gray-500">
            Range: <span className="text-gray-400">{meta.min ?? "–"} to {meta.max ?? "–"}</span>
          </p>
        )}
      </span>
    </span>
  );
}

function FieldLabel({ meta }: { meta: SettingFieldMeta }) {
  return (
    <div className="flex items-center gap-1.5 mb-1">
      <label className="text-xs text-gray-400">{meta.label}</label>
      <InfoTooltip meta={meta} />
      <RestartBadge behavior={meta.restart_behavior} />
    </div>
  );
}

// ── Generic field components ────────────────────────────────────────────────

function NumberInput({
  meta,
  value,
  error,
  onChange,
}: {
  meta: SettingFieldMeta;
  value: number;
  error?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <FieldLabel meta={meta} />
      <input
        type="number"
        value={value}
        min={meta.min ?? undefined}
        max={meta.max ?? undefined}
        step={meta.type === "float" ? 0.05 : 1}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`w-full bg-gray-800 border text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 ${
          error ? "border-red-600 focus:ring-red-600" : "border-gray-700 focus:ring-indigo-500"
        }`}
      />
      {error && <p className="text-xs text-red-400 mt-0.5">{error}</p>}
    </div>
  );
}

function TextInput({
  meta,
  value,
  error,
  onChange,
}: {
  meta: SettingFieldMeta;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <FieldLabel meta={meta} />
      <input
        type="text"
        value={value}
        placeholder={meta.placeholder ?? undefined}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-gray-800 border text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 ${
          error ? "border-red-600 focus:ring-red-600" : "border-gray-700 focus:ring-indigo-500"
        }`}
      />
      {error && <p className="text-xs text-red-400 mt-0.5">{error}</p>}
    </div>
  );
}

function TimeInput({
  meta,
  value,
  error,
  onChange,
}: {
  meta: SettingFieldMeta;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <FieldLabel meta={meta} />
      <input
        type="time"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-gray-800 border text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 [color-scheme:dark] ${
          error ? "border-red-600 focus:ring-red-600" : "border-gray-700 focus:ring-indigo-500"
        }`}
      />
      {error && <p className="text-xs text-red-400 mt-0.5">{error}</p>}
    </div>
  );
}

function SelectInput({
  meta,
  value,
  error,
  onChange,
}: {
  meta: SettingFieldMeta;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <FieldLabel meta={meta} />
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full bg-gray-800 border text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 ${
          error ? "border-red-600 focus:ring-red-600" : "border-gray-700 focus:ring-indigo-500"
        }`}
      >
        {(meta.choices ?? []).map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
      {error && <p className="text-xs text-red-400 mt-0.5">{error}</p>}
    </div>
  );
}

function ToggleInput({
  meta,
  value,
  onChange,
}: {
  meta: SettingFieldMeta;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-1.5">
        <span className="text-sm text-gray-300">{meta.label}</span>
        <InfoTooltip meta={meta} />
        <RestartBadge behavior={meta.restart_behavior} />
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors shrink-0 ${
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

// media_storage_chat_id is the one nullable scalar (blank clears it back to
// "fall back to first admin ID") — rendered as text so it can be emptied.
const NULLABLE_TEXT_FIELDS = new Set(["media_storage_chat_id"]);

function SettingField({
  meta,
  value,
  error,
  onChange,
}: {
  meta: SettingFieldMeta;
  value: string | number | boolean | null;
  error?: string;
  onChange: (v: string | number | boolean) => void;
}) {
  if (meta.type === "bool") {
    return <ToggleInput meta={meta} value={Boolean(value)} onChange={onChange} />;
  }
  if (meta.widget === "time") {
    return <TimeInput meta={meta} value={value === null ? "" : String(value)} error={error} onChange={onChange} />;
  }
  if (meta.widget === "select") {
    return <SelectInput meta={meta} value={String(value ?? "")} error={error} onChange={onChange} />;
  }
  if (NULLABLE_TEXT_FIELDS.has(meta.key)) {
    return <TextInput meta={meta} value={value === null ? "" : String(value)} error={error} onChange={onChange} />;
  }
  if (meta.type === "int" || meta.type === "float") {
    return <NumberInput meta={meta} value={Number(value ?? 0)} error={error} onChange={onChange} />;
  }
  return <TextInput meta={meta} value={String(value ?? "")} error={error} onChange={onChange} />;
}

// ── Section wrapper ──────────────────────────────────────────────────────────

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

// ── Membership channels ──────────────────────────────────────────────────────

const MAX_MEMBERSHIP_CHANNELS = 5;

function MembershipChannelsCard() {
  const queryClient = useQueryClient();
  const { data: channels, isLoading } = useQuery({
    queryKey: ["admin", "settings", "membership-channels"],
    queryFn: getMembershipChannels,
  });

  const [rows, setRows] = useState<MembershipChannel[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (channels) {
      setRows(channels.map((c) => ({ ...c })));
      setDirty(false);
    }
  }, [channels]);

  const mutation = useMutation({
    mutationFn: putMembershipChannels,
    onSuccess: (updated) => {
      queryClient.setQueryData(["admin", "settings", "membership-channels"], updated);
      queryClient.invalidateQueries({ queryKey: ["admin", "settings", "history"] });
      toast.success("Membership channels saved");
      setDirty(false);
    },
    onError: (err) => toast.error(extractErrorMessage(err) ?? "Failed to save membership channels"),
  });

  if (isLoading || !rows) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-4 text-sm text-gray-500 animate-pulse">
        Loading membership channels…
      </div>
    );
  }

  const rowErrors = rows.map((r) => ({
    id: validateMembershipChannelId(r.id),
    url: validateMembershipChannelUrl(r.url),
  }));
  const hasErrors = rowErrors.some((e) => e.id || e.url);

  function updateRow(i: number, patch: Partial<MembershipChannel>) {
    setRows((prev) => (prev ? prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) : prev));
    setDirty(true);
  }
  function removeRow(i: number) {
    setRows((prev) => (prev ? prev.filter((_, idx) => idx !== i) : prev));
    setDirty(true);
  }
  function addRow() {
    setRows((prev) => (prev && prev.length < MAX_MEMBERSHIP_CHANNELS ? [...prev, { id: 0, url: "" }] : prev));
    setDirty(true);
  }
  function moveRow(i: number, dir: -1 | 1) {
    setRows((prev) => {
      if (!prev) return prev;
      const j = i + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
    setDirty(true);
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-5 py-4 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-sm font-medium text-white flex items-center gap-2">
          Membership Channels
          {dirty && (
            <span className="inline-block w-2 h-2 rounded-full bg-amber-400" title="Unsaved changes" />
          )}
          <RestartBadge behavior="live" />
        </span>
        <span className="text-gray-500 text-xs">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-5 pb-5 space-y-3">
          <p className="text-xs text-gray-500">
            Mandatory channels users must join before using the bot. The bot must already be an
            admin member of a channel before it&apos;s added here — otherwise membership checks
            against it will always fail.
          </p>

          {rows.length === 0 && (
            <p className="text-xs text-gray-600">
              No membership channels configured — the join gate is disabled.
            </p>
          )}

          {rows.map((row, i) => (
            <div key={i} className="flex items-start gap-2">
              <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <input
                    type="number"
                    value={row.id}
                    placeholder="-1001234567890"
                    onChange={(e) => updateRow(i, { id: Number(e.target.value) })}
                    className={`w-full bg-gray-800 border text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 ${
                      rowErrors[i].id ? "border-red-600" : "border-gray-700 focus:ring-indigo-500"
                    }`}
                  />
                  {rowErrors[i].id && <p className="text-xs text-red-400 mt-0.5">{rowErrors[i].id}</p>}
                </div>
                <div>
                  <input
                    type="text"
                    value={row.url}
                    placeholder="https://t.me/yourchannel"
                    onChange={(e) => updateRow(i, { url: e.target.value })}
                    className={`w-full bg-gray-800 border text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 ${
                      rowErrors[i].url ? "border-red-600" : "border-gray-700 focus:ring-indigo-500"
                    }`}
                  />
                  {rowErrors[i].url && <p className="text-xs text-red-400 mt-0.5">{rowErrors[i].url}</p>}
                </div>
              </div>
              <div className="flex flex-col gap-1 pt-0.5">
                <button
                  type="button"
                  onClick={() => moveRow(i, -1)}
                  disabled={i === 0}
                  className="text-gray-500 hover:text-white disabled:opacity-30 text-xs px-1"
                >
                  ▲
                </button>
                <button
                  type="button"
                  onClick={() => moveRow(i, 1)}
                  disabled={i === rows.length - 1}
                  className="text-gray-500 hover:text-white disabled:opacity-30 text-xs px-1"
                >
                  ▼
                </button>
              </div>
              <button
                type="button"
                onClick={() => removeRow(i)}
                className="text-red-500 hover:text-red-400 text-xs px-2 pt-1.5"
              >
                Remove
              </button>
            </div>
          ))}

          <div className="flex items-center justify-between pt-1">
            <button
              type="button"
              onClick={addRow}
              disabled={rows.length >= MAX_MEMBERSHIP_CHANNELS}
              className="text-xs text-indigo-400 hover:text-indigo-300 disabled:opacity-30"
            >
              + Add channel
            </button>
            <button
              onClick={() => mutation.mutate(rows)}
              disabled={mutation.isPending || !dirty || hasErrors}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {mutation.isPending ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const queryClient = useQueryClient();

  const { data: metadata, isLoading: metaLoading } = useQuery({
    queryKey: ["admin", "settings", "metadata"],
    queryFn: getSettingsMetadata,
  });
  const { data: settingsData, isLoading: valuesLoading } = useQuery({
    queryKey: ["admin", "settings"],
    queryFn: getSettings,
  });
  const { data: history } = useQuery({
    queryKey: ["admin", "settings", "history"],
    queryFn: getSettingsHistory,
  });

  const [values, setValues] = useState<SettingsValues | null>(null);
  const [dirtyCategories, setDirtyCategories] = useState<Set<string>>(new Set());
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    if (settingsData) {
      setValues(JSON.parse(JSON.stringify(settingsData)));
      setDirtyCategories(new Set());
      setFieldErrors({});
    }
  }, [settingsData]);

  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirtyCategories.size > 0) e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirtyCategories]);

  const mutation = useMutation({
    mutationFn: patchSettings,
    onSuccess: (updated) => {
      queryClient.setQueryData(["admin", "settings"], updated);
      queryClient.invalidateQueries({ queryKey: ["admin", "settings", "history"] });
      toast.success("Settings saved");
    },
    onError: (err) => toast.error(extractErrorMessage(err) ?? "Failed to save settings"),
  });

  if (metaLoading || valuesLoading || !metadata || !values) {
    return (
      <div className="flex items-center justify-center h-64">
        <span className="text-gray-500 animate-pulse">Loading settings…</span>
      </div>
    );
  }

  function handleFieldChange(categoryKey: string, meta: SettingFieldMeta, raw: string | number | boolean) {
    setValues((prev) => (prev ? { ...prev, [categoryKey]: { ...prev[categoryKey], [meta.key]: raw } } : prev));
    setDirtyCategories((prev) => new Set(prev).add(categoryKey));
    setFieldErrors((prev) => {
      const next = { ...prev };
      const errKey = `${categoryKey}.${meta.key}`;
      const err = validateFieldValue(meta, raw);
      if (err) next[errKey] = err;
      else delete next[errKey];
      return next;
    });
  }

  function handleSaveCategory(category: SettingCategoryMeta) {
    if (!values) return;
    const hasErrors = category.fields.some((f) => fieldErrors[`${category.key}.${f.key}`]);
    if (hasErrors) {
      toast.error("Fix validation errors before saving");
      return;
    }
    mutation.mutate({ [category.key]: values[category.key] });
    setDirtyCategories((prev) => {
      const next = new Set(prev);
      next.delete(category.key);
      return next;
    });
  }

  return (
    <div className="space-y-5 max-w-3xl">
      <h1 className="text-xl font-semibold text-white">Settings</h1>

      <div className="bg-gray-900/60 border border-gray-800 rounded-lg px-4 py-3 text-xs text-gray-400">
        Every field shows a badge for how the change takes effect — hover it for details. Hover
        the ⓘ next to a field's label for its description, example, and valid range.
      </div>

      {metadata.map((category) => (
        <Section
          key={category.key}
          title={category.label}
          dirty={dirtyCategories.has(category.key)}
          saving={mutation.isPending}
          onSave={() => handleSaveCategory(category)}
        >
          {category.fields.map((meta) => (
            <div key={meta.key} className={meta.type === "bool" ? "sm:col-span-2" : undefined}>
              <SettingField
                meta={meta}
                value={values[category.key]?.[meta.key] ?? null}
                error={fieldErrors[`${category.key}.${meta.key}`]}
                onChange={(v) => handleFieldChange(category.key, meta, v)}
              />
            </div>
          ))}
        </Section>
      ))}

      <MembershipChannelsCard />

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
                      <td className="px-4 py-2 text-gray-600 max-w-xs truncate" title={h.old_value}>
                        {h.old_value}
                      </td>
                      <td className="px-4 py-2 text-green-400 max-w-xs truncate" title={h.new_value}>
                        {h.new_value}
                      </td>
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
