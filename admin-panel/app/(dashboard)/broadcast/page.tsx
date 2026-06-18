"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useMemo, type ReactNode } from "react";
import toast from "react-hot-toast";
import { getChannels } from "@/lib/api/reservations";
import { getCountries } from "@/lib/api/users";
import {
  sendManualBroadcast,
  triggerDailyBroadcast,
  getBroadcastLogs,
  previewUserAudience,
  createUserBroadcast,
  getUserBroadcast,
  getUserBroadcasts,
  uploadMedia,
  sendDraft,
  getTemplates,
  createTemplate,
  updateTemplate,
  deleteTemplate,
  getRecurringRules,
  deactivateRecurringRule,
  AUDIENCE_LABELS,
  type BroadcastChannelResult,
  type UserAudience,
  type UserBroadcastStatus,
  type UserBroadcastHistoryItem,
  type SegmentFilter,
  type SegmentRequest,
  type AudiencePreview,
  type ReservationStatus,
  type Gender,
  type MediaKind,
  type RecurrenceSpec,
  type CreateBroadcastParams,
  type BroadcastTemplate,
  type TemplateInput,
  type RecurringRule,
} from "@/lib/api/broadcast";

type Tab = "channels" | "users" | "templates" | "recurring" | "history";
type ChannelSubTab = "custom" | "daily";
type ParseMode = "HTML" | "Markdown" | "plain";

function StatusBadge({ success }: { success: boolean }) {
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
        success ? "bg-green-900/60 text-green-400" : "bg-red-900/60 text-red-400"
      }`}
    >
      {success ? "Sent" : "Failed"}
    </span>
  );
}

function BroadcastStatusBadge({ status }: { status: UserBroadcastStatus }) {
  const map: Record<UserBroadcastStatus, string> = {
    draft: "bg-gray-800 text-gray-400 border border-gray-600",
    pending: "bg-gray-700 text-gray-300",
    scheduled: "bg-purple-900/60 text-purple-300",
    processing: "bg-blue-900/60 text-blue-300",
    completed: "bg-green-900/60 text-green-400",
    failed: "bg-red-900/60 text-red-400",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium capitalize ${map[status]}`}>
      {status}
    </span>
  );
}

function ChannelSelector({
  channels,
  selected,
  onChange,
}: {
  channels: { id: string; name: string }[];
  selected: Set<string>;
  onChange: (ids: Set<string>) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex gap-3 text-xs">
        <button
          onClick={() => onChange(new Set(channels.map((c) => c.id)))}
          className="text-indigo-400 hover:text-indigo-300"
        >
          Select all
        </button>
        <button onClick={() => onChange(new Set())} className="text-gray-500 hover:text-gray-300">
          Deselect all
        </button>
      </div>
      <div className="space-y-1.5">
        {channels.map((ch) => (
          <label key={ch.id} className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={selected.has(ch.id)}
              onChange={(e) => {
                const next = new Set(selected);
                e.target.checked ? next.add(ch.id) : next.delete(ch.id);
                onChange(next);
              }}
              className="accent-indigo-500"
            />
            <span className="text-sm text-gray-300">{ch.name}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

function ResultsTable({ results }: { results: BroadcastChannelResult[] }) {
  if (results.length === 0) return null;
  return (
    <div className="mt-4 bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-800 text-gray-500 text-xs">
          <tr>
            <th className="px-4 py-2 text-left">Channel</th>
            <th className="px-4 py-2 text-left">Result</th>
            <th className="px-4 py-2 text-left">Error</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r, i) => (
            <tr key={i} className="border-t border-gray-800">
              <td className="px-4 py-2 text-gray-300">{r.channel_name ?? r.channel_id}</td>
              <td className="px-4 py-2">
                <StatusBadge success={r.success} />
              </td>
              <td className="px-4 py-2 text-xs text-red-400">{r.error ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ParseModeSelector({
  value,
  onChange,
}: {
  value: ParseMode;
  onChange: (m: ParseMode) => void;
}) {
  return (
    <div className="flex gap-3">
      {(["HTML", "Markdown", "plain"] as ParseMode[]).map((m) => (
        <label key={m} className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-300">
          <input
            type="radio"
            name="parse_mode"
            checked={value === m}
            onChange={() => onChange(m)}
            className="accent-indigo-500"
          />
          {m}
        </label>
      ))}
    </div>
  );
}

// ── Custom message (channels) ───────────────────────────────────────────────

function CustomMessageTab({ channels }: { channels: { id: string; name: string }[] }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [parseMode, setParseMode] = useState<ParseMode>("HTML");
  const [message, setMessage] = useState("");
  const [results, setResults] = useState<BroadcastChannelResult[]>([]);

  const mutation = useMutation({
    mutationFn: sendManualBroadcast,
    onSuccess: (data) => {
      setResults(data);
      const ok = data.filter((r) => r.success).length;
      const fail = data.length - ok;
      if (fail === 0) toast.success(`Sent to ${ok} channel${ok !== 1 ? "s" : ""}`);
      else toast.error(`${fail} channel(s) failed — see results below`);
    },
    onError: (err: any) => {
      if (err?.response?.status === 429) toast.error("Rate limit exceeded. Wait a few minutes.");
      else toast.error("Broadcast failed");
    },
  });

  function handleSend() {
    if (selected.size === 0) return toast.error("Select at least one channel");
    if (message.trim().length < 10) return toast.error("Message too short (min 10 chars)");
    if (!confirm(`Send to ${selected.size} channel${selected.size !== 1 ? "s" : ""}?`)) return;
    mutation.mutate({
      channel_ids: Array.from(selected),
      message: message.trim(),
      parse_mode: parseMode,
    });
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Channels</p>
            <ChannelSelector channels={channels} selected={selected} onChange={setSelected} />
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Parse mode</p>
            <ParseModeSelector value={parseMode} onChange={setParseMode} />
          </div>
          <div>
            <div className="flex justify-between items-center mb-1">
              <p className="text-xs text-gray-500 uppercase tracking-wider">Message</p>
              <span className={`text-xs ${message.length > 3800 ? "text-red-400" : "text-gray-500"}`}>
                {message.length} / 4000
              </span>
            </div>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={4000}
              rows={8}
              placeholder="Your message here…"
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 resize-y placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <button
            onClick={handleSend}
            disabled={mutation.isPending}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {mutation.isPending ? "Sending…" : `Send to ${selected.size} channel${selected.size !== 1 ? "s" : ""}`}
          </button>
        </div>
        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Preview</p>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 min-h-[200px] text-sm text-gray-300 whitespace-pre-wrap break-words">
            {message || <span className="text-gray-600">Preview appears here…</span>}
          </div>
        </div>
      </div>
      <ResultsTable results={results} />
    </div>
  );
}

// ── Daily schedule (channels) ───────────────────────────────────────────────

function DailyScheduleTab({ channels }: { channels: { id: string; name: string }[] }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<BroadcastChannelResult[]>([]);

  const { data: todayLogs } = useQuery({
    queryKey: ["admin", "broadcast", "logs", "today"],
    queryFn: () => getBroadcastLogs({ page: 1, page_size: 100 }),
  });

  const sentToday = new Set<string>(
    (todayLogs?.items ?? [])
      .filter((l) => l.status === "sent" && l.channel_id)
      .map((l) => l.channel_id as string)
  );
  const sentAtMap: Record<string, string> = {};
  (todayLogs?.items ?? []).forEach((l) => {
    if (l.status === "sent" && l.channel_id) sentAtMap[l.channel_id] = l.sent_at;
  });

  const mutation = useMutation({
    mutationFn: triggerDailyBroadcast,
    onSuccess: (data) => {
      setResults(data);
      const ok = data.filter((r) => r.success).length;
      toast.success(`Daily broadcast sent to ${ok} channel${ok !== 1 ? "s" : ""}`);
    },
    onError: (err: any) => {
      if (err?.response?.status === 409) {
        const detail = err.response.data?.detail;
        const alreadySent = detail?.already_sent ?? [];
        const names = alreadySent.map((c: any) => c.channel_name ?? c.channel_id).join(", ");
        toast.error(`Already sent today: ${names}`);
      } else {
        toast.error("Failed to trigger daily broadcast");
      }
    },
  });

  function handleTrigger() {
    const ids = selected.size > 0 ? Array.from(selected) : null;
    mutation.mutate({ channel_ids: ids });
  }

  return (
    <div className="space-y-5">
      <div className="bg-amber-900/20 border border-amber-700/40 rounded-lg px-4 py-3 text-sm text-amber-300">
        This sends the same broadcast the scheduler would send. Channels where today&apos;s
        broadcast was already sent will cause a 409 error — deselect them first.
      </div>
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-3">Channels</p>
        <div className="space-y-2">
          <div className="flex gap-3 text-xs">
            <button
              onClick={() => setSelected(new Set(channels.map((c) => c.id)))}
              className="text-indigo-400 hover:text-indigo-300"
            >
              Select all
            </button>
            <button onClick={() => setSelected(new Set())} className="text-gray-500 hover:text-gray-300">
              Deselect all
            </button>
          </div>
          {channels.map((ch) => {
            const alreadySent = sentToday.has(ch.id);
            const sentAt = sentAtMap[ch.id];
            return (
              <label
                key={ch.id}
                className={`flex items-center gap-2 cursor-pointer ${alreadySent ? "opacity-60" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(ch.id)}
                  onChange={(e) => {
                    const next = new Set(selected);
                    e.target.checked ? next.add(ch.id) : next.delete(ch.id);
                    setSelected(next);
                  }}
                  className="accent-indigo-500"
                />
                <span className="text-sm text-gray-300">{ch.name}</span>
                {alreadySent && (
                  <span className="ml-1 text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                    Sent today {sentAt ? `at ${new Date(sentAt).toLocaleTimeString()}` : ""}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      </div>
      <button
        onClick={handleTrigger}
        disabled={mutation.isPending}
        className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
      >
        {mutation.isPending ? "Sending…" : "Trigger daily broadcast"}
      </button>
      <ResultsTable results={results} />
    </div>
  );
}

// ── Channel broadcast log ────────────────────────────────────────────────────

function BroadcastLogSection({ channels }: { channels: { id: string; name: string }[] }) {
  const today = new Date().toISOString().slice(0, 10);
  const [logDate, setLogDate] = useState(today);
  const [logChannel, setLogChannel] = useState("");
  const [page, setPage] = useState(1);

  const { data } = useQuery({
    queryKey: ["admin", "broadcast", "logs", { logDate, logChannel, page }],
    queryFn: () =>
      getBroadcastLogs({
        date: logDate,
        ...(logChannel ? { channel_id: logChannel } : {}),
        page,
        page_size: 50,
      }),
  });

  return (
    <div className="space-y-4">
      <h2 className="text-sm font-medium text-white">Channel broadcast log</h2>
      <div className="flex flex-wrap gap-3">
        <input
          type="date"
          value={logDate}
          onChange={(e) => { setLogDate(e.target.value); setPage(1); }}
          className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
        <select
          value={logChannel}
          onChange={(e) => { setLogChannel(e.target.value); setPage(1); }}
          className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All channels</option>
          {channels.map((ch) => (
            <option key={ch.id} value={ch.id}>{ch.name}</option>
          ))}
        </select>
      </div>
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-500 text-xs">
            <tr>
              <th className="px-4 py-2 text-left">Date</th>
              <th className="px-4 py-2 text-left">Channel</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Msg ID</th>
              <th className="px-4 py-2 text-left">Sent at</th>
              <th className="px-4 py-2 text-left">Error</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-gray-600 text-sm">
                  No logs for this date
                </td>
              </tr>
            ) : (
              (data?.items ?? []).map((log) => (
                <tr key={log.id} className="border-t border-gray-800">
                  <td className="px-4 py-2 text-gray-400 text-xs">{log.broadcast_date}</td>
                  <td className="px-4 py-2 text-gray-300">{log.channel_name ?? "—"}</td>
                  <td className="px-4 py-2">
                    <StatusBadge success={log.status === "sent"} />
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">{log.telegram_message_id ?? "—"}</td>
                  <td className="px-4 py-2 text-xs text-gray-400">
                    {new Date(log.sent_at).toLocaleTimeString()}
                  </td>
                  <td className="px-4 py-2 text-xs text-red-400">{log.error_message ?? ""}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {(data?.pages ?? 1) > 1 && (
        <div className="flex gap-2 justify-end text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-md text-gray-400 hover:text-white disabled:opacity-40"
          >
            ← Prev
          </button>
          <span className="px-2 py-1.5 text-gray-500">{page} / {data?.pages}</span>
          <button
            onClick={() => setPage((p) => Math.min(data!.pages, p + 1))}
            disabled={page >= (data?.pages ?? 1)}
            className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-md text-gray-400 hover:text-white disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

// ── Channels tab (wraps custom + daily) ──────────────────────────────────────

function ChannelsTab({ channels }: { channels: { id: string; name: string }[] }) {
  const [sub, setSub] = useState<ChannelSubTab>("custom");
  return (
    <div className="space-y-6">
      <div className="flex rounded-lg overflow-hidden border border-gray-700 text-sm w-fit">
        {(["custom", "daily"] as ChannelSubTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setSub(t)}
            className={`px-5 py-2 transition-colors ${
              sub === t ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"
            }`}
          >
            {t === "custom" ? "Custom message" : "Daily schedule"}
          </button>
        ))}
      </div>
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        {sub === "custom" ? (
          <CustomMessageTab channels={channels} />
        ) : (
          <DailyScheduleTab channels={channels} />
        )}
      </div>
      <BroadcastLogSection channels={channels} />
    </div>
  );
}

// ── Live progress panel ──────────────────────────────────────────────────────

function ProgressPanel({ broadcastId }: { broadcastId: string }) {
  const { data } = useQuery({
    queryKey: ["admin", "user-broadcast", broadcastId],
    queryFn: () => getUserBroadcast(broadcastId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "completed" || s === "failed" ? false : 2000;
    },
  });

  if (!data) return null;

  return (
    <div className="bg-gray-950 border border-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-300">Delivery</span>
        <BroadcastStatusBadge status={data.status} />
      </div>
      <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
        <div
          className="bg-indigo-500 h-2 transition-all"
          style={{ width: `${data.progress_percent}%` }}
        />
      </div>
      <div className="grid grid-cols-4 gap-3 text-center text-sm">
        <Metric label="Total" value={data.total_recipients} />
        <Metric label="Sent" value={data.success_count} tone="text-green-400" />
        <Metric label="Failed" value={data.failed_count} tone="text-red-400" />
        <Metric label="Blocked" value={data.blocked_count} tone="text-amber-400" />
      </div>
      <p className="text-xs text-gray-500 text-right">{data.progress_percent}%</p>
    </div>
  );
}

function Metric({ label, value, tone = "text-gray-200" }: { label: string; value: number; tone?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg py-2">
      <p className={`text-lg font-semibold ${tone}`}>{value}</p>
      <p className="text-xs text-gray-500">{label}</p>
    </div>
  );
}

// ── Users tab ────────────────────────────────────────────────────────────────

type SegmentMode = "quick" | "advanced";
type TriState = "any" | "yes" | "no";

const RESERVATION_STATUSES: ReservationStatus[] = ["active", "completed", "cancelled", "expired"];
const GENDERS: { value: Gender; label: string }[] = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "not_say", label: "Not specified" },
];

function CheckboxGroup<T extends string>({
  options,
  selected,
  onToggle,
}: {
  options: { value: T; label: string }[];
  selected: Set<T>;
  onToggle: (v: T) => void;
}) {
  return (
    <div className="flex flex-wrap gap-3">
      {options.map((o) => (
        <label key={o.value} className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-300">
          <input
            type="checkbox"
            checked={selected.has(o.value)}
            onChange={() => onToggle(o.value)}
            className="accent-indigo-500"
          />
          {o.label}
        </label>
      ))}
    </div>
  );
}

function TriStateSelect({ value, onChange }: { value: TriState; onChange: (v: TriState) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as TriState)}
      className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
    >
      <option value="any">Any</option>
      <option value="yes">Yes</option>
      <option value="no">No</option>
    </select>
  );
}

function UsersTab({
  prefillTemplate,
  clearPrefill,
}: {
  prefillTemplate: BroadcastTemplate | null;
  clearPrefill: () => void;
}) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<SegmentMode>("quick");
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [parseMode, setParseMode] = useState<ParseMode>("HTML");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState<AudiencePreview | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [activeBroadcastId, setActiveBroadcastId] = useState<string | null>(null);

  // Media
  const [mediaType, setMediaType] = useState<MediaKind>("text");
  const [mediaFileId, setMediaFileId] = useState<string | null>(null);
  const [mediaName, setMediaName] = useState<string>("");
  const [uploading, setUploading] = useState(false);

  // Delivery
  const [deliveryMode, setDeliveryMode] = useState<"now" | "schedule" | "recurring">("now");
  const [scheduledFor, setScheduledFor] = useState("");
  const [frequency, setFrequency] = useState<"daily" | "weekly" | "monthly">("daily");
  const [interval, setIntervalVal] = useState(1);
  const [dayOfWeek, setDayOfWeek] = useState(0);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [timeOfDay, setTimeOfDay] = useState("");

  // Quick segment
  const [audience, setAudience] = useState<UserAudience>("all_users");

  // Advanced filters
  const [scoreMin, setScoreMin] = useState("");
  const [scoreMax, setScoreMax] = useState("");
  const [resStatuses, setResStatuses] = useState<Set<ReservationStatus>>(new Set());
  const [hasNoShow, setHasNoShow] = useState<TriState>("any");
  const [hasUsername, setHasUsername] = useState<TriState>("any");
  const [countryIds, setCountryIds] = useState<Set<string>>(new Set());
  const [countrySearch, setCountrySearch] = useState("");
  const [genders, setGenders] = useState<Set<Gender>>(new Set());
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");

  const { data: countries = [] } = useQuery({
    queryKey: ["admin", "countries"],
    queryFn: getCountries,
    staleTime: 10 * 60 * 1000,
  });

  // Prefill from a template chosen in the Templates tab.
  useEffect(() => {
    if (prefillTemplate) {
      setMessage(prefillTemplate.message);
      setParseMode(prefillTemplate.parse_mode);
      setMediaType(prefillTemplate.media_type);
      setMediaFileId(prefillTemplate.media_file_id);
      setMediaName(prefillTemplate.media_file_id ? "from template" : "");
      setTemplateId(prefillTemplate.id);
      toast.success(`Loaded template “${prefillTemplate.name}”`);
      clearPrefill();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillTemplate]);

  const saveTemplateMut = useMutation({
    mutationFn: async () => {
      const name = window.prompt("Template name?");
      if (!name) throw new Error("cancelled");
      return createTemplate({
        name,
        message: message.trim(),
        parse_mode: parseMode,
        media_type: mediaType,
        media_file_id: mediaType === "text" ? null : mediaFileId,
      });
    },
    onSuccess: () => {
      toast.success("Saved as template");
      queryClient.invalidateQueries({ queryKey: ["admin", "templates"] });
    },
    onError: (e: any) => {
      if (e?.message !== "cancelled") toast.error("Failed to save template");
    },
  });

  function buildFilters(): SegmentFilter {
    const f: SegmentFilter = {};
    if (scoreMin !== "" || scoreMax !== "") {
      f.score = {
        min: scoreMin === "" ? null : Number(scoreMin),
        max: scoreMax === "" ? null : Number(scoreMax),
      };
    }
    if (resStatuses.size) f.reservation_statuses = Array.from(resStatuses);
    if (hasNoShow !== "any") f.has_no_show = hasNoShow === "yes";
    if (hasUsername !== "any") f.has_username = hasUsername === "yes";
    if (countryIds.size) f.country_ids = Array.from(countryIds);
    if (genders.size) f.genders = Array.from(genders);
    if (createdFrom) f.created_from = new Date(`${createdFrom}T00:00:00`).toISOString();
    if (createdTo) f.created_to = new Date(`${createdTo}T23:59:59`).toISOString();
    return f;
  }

  // The current request — quick segment OR advanced filters.
  const request: SegmentRequest = useMemo(
    () => (mode === "quick" ? { audience_type: audience } : { filters: buildFilters() }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, audience, scoreMin, scoreMax, resStatuses, hasNoShow, hasUsername, countryIds, genders, createdFrom, createdTo]
  );

  // Any change to the request invalidates a previously fetched preview.
  const reqKey = JSON.stringify(request);
  useEffect(() => {
    setPreview(null);
  }, [reqKey]);

  const previewMutation = useMutation({
    mutationFn: () => previewUserAudience(request),
    onSuccess: (d) => setPreview(d),
    onError: () => toast.error("Failed to load audience preview"),
  });

  const createMutation = useMutation({
    mutationFn: createUserBroadcast,
    onSuccess: (d) => {
      setActiveBroadcastId(d.id);
      setConfirmOpen(false);
      toast.success(`Broadcast queued for ${d.total_recipients} user${d.total_recipients !== 1 ? "s" : ""}`);
      queryClient.invalidateQueries({ queryKey: ["admin", "user-broadcasts"] });
    },
    onError: (err: any) => {
      setConfirmOpen(false);
      if (err?.response?.status === 429) toast.error("Rate limit exceeded. Wait a few minutes.");
      else toast.error("Failed to create broadcast");
    },
  });

  function buildCreateParams(): CreateBroadcastParams {
    const base: CreateBroadcastParams = {
      parse_mode: parseMode,
      message: message.trim() || undefined,
      media_type: mediaType,
      media_file_id: mediaType === "text" ? null : mediaFileId,
      ...(templateId ? { template_id: templateId } : {}),
      ...(mode === "quick" ? { audience_type: audience } : { filters: buildFilters() }),
    };
    if (deliveryMode === "schedule" && scheduledFor) {
      base.scheduled_for = new Date(scheduledFor).toISOString();
    }
    if (deliveryMode === "recurring") {
      const rec: RecurrenceSpec = { frequency, interval };
      if (frequency === "weekly") rec.day_of_week = dayOfWeek;
      if (frequency === "monthly") rec.day_of_month = dayOfMonth;
      if (timeOfDay) rec.time_of_day = timeOfDay;
      base.recurrence = rec;
    }
    return base;
  }

  function contentValid(): boolean {
    if (mediaType !== "text" && !mediaFileId) {
      toast.error("Upload a file first");
      return false;
    }
    if (mediaType === "text" && message.trim().length < 1) {
      toast.error("Message is empty");
      return false;
    }
    return true;
  }

  async function handleSendClick() {
    if (!contentValid()) return;
    if (deliveryMode === "schedule" && !scheduledFor) return toast.error("Pick a date/time");
    let p = preview;
    if (p === null) p = await previewMutation.mutateAsync();
    if (deliveryMode === "now" && p.count === 0) return toast.error("No users match this segment");
    setConfirmOpen(true);
  }

  function confirmSend() {
    createMutation.mutate(buildCreateParams());
  }

  const saveDraftMutation = useMutation({
    mutationFn: () => createUserBroadcast({ ...buildCreateParams(), save_as_draft: true }),
    onSuccess: () => {
      toast.success("Draft saved");
      queryClient.invalidateQueries({ queryKey: ["admin", "user-broadcasts"] });
    },
    onError: () => toast.error("Failed to save draft"),
  });

  async function handleUpload(file: File) {
    if (mediaType === "text") return;
    setUploading(true);
    try {
      const res = await uploadMedia(file, mediaType);
      setMediaFileId(res.media_file_id);
      setMediaName(file.name);
      toast.success("Media uploaded");
    } catch {
      toast.error("Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const confirmCount = preview?.count ?? 0;
  const primaryLabel =
    deliveryMode === "schedule"
      ? "Schedule Broadcast"
      : deliveryMode === "recurring"
      ? "Create Recurring"
      : "Send Broadcast";

  function toggle<T>(set: Set<T>, setter: (s: Set<T>) => void, v: T) {
    const next = new Set(set);
    next.has(v) ? next.delete(v) : next.add(v);
    setter(next);
  }

  return (
    <div className="space-y-5">
      {/* Mode toggle */}
      <div className="flex rounded-lg overflow-hidden border border-gray-700 text-sm w-fit">
        {(["quick", "advanced"] as SegmentMode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-5 py-2 transition-colors ${
              mode === m ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"
            }`}
          >
            {m === "quick" ? "Quick segment" : "Advanced segment"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="space-y-4">
          {mode === "quick" ? (
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Audience</p>
              <select
                value={audience}
                onChange={(e) => setAudience(e.target.value as UserAudience)}
                className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {(["all_users", "active_users", "users_with_reservations"] as UserAudience[]).map((a) => (
                  <option key={a} value={a}>{AUDIENCE_LABELS[a]}</option>
                ))}
              </select>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Score range</p>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    value={scoreMin}
                    onChange={(e) => setScoreMin(e.target.value)}
                    placeholder="Min"
                    className="w-24 bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <span className="text-gray-600">—</span>
                  <input
                    type="number"
                    value={scoreMax}
                    onChange={(e) => setScoreMax(e.target.value)}
                    placeholder="Max"
                    className="w-24 bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Reservation status</p>
                <CheckboxGroup
                  options={RESERVATION_STATUSES.map((s) => ({ value: s, label: s }))}
                  selected={resStatuses}
                  onToggle={(v) => toggle(resStatuses, setResStatuses, v)}
                />
              </div>

              <div className="flex gap-8">
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">No-show</p>
                  <TriStateSelect value={hasNoShow} onChange={setHasNoShow} />
                </div>
                <div>
                  <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Has username</p>
                  <TriStateSelect value={hasUsername} onChange={setHasUsername} />
                </div>
              </div>

              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Gender</p>
                <CheckboxGroup
                  options={GENDERS}
                  selected={genders}
                  onToggle={(v) => toggle(genders, setGenders, v)}
                />
              </div>

              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Country</p>
                <input
                  type="text"
                  value={countrySearch}
                  onChange={(e) => setCountrySearch(e.target.value)}
                  placeholder="Search countries…"
                  className="w-full mb-2 bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
                <div className="max-h-32 overflow-y-auto border border-gray-700 rounded-md p-2 space-y-1">
                  {(() => {
                    const term = countrySearch.trim().toLowerCase();
                    const filtered = term
                      ? countries.filter((c) => c.name.toLowerCase().includes(term))
                      : countries;
                    if (countries.length === 0)
                      return <span className="text-xs text-gray-600">No countries</span>;
                    if (filtered.length === 0)
                      return <span className="text-xs text-gray-600">No matches</span>;
                    return filtered.map((c) => (
                      <label key={c.id} className="flex items-center gap-2 cursor-pointer text-sm text-gray-300">
                        <input
                          type="checkbox"
                          checked={countryIds.has(c.id)}
                          onChange={() => toggle(countryIds, setCountryIds, c.id)}
                          className="accent-indigo-500"
                        />
                        {c.flag_emoji ? `${c.flag_emoji} ` : ""}{c.name}
                      </label>
                    ));
                  })()}
                </div>
                {countryIds.size > 0 && (
                  <p className="mt-1 text-xs text-gray-500">{countryIds.size} selected</p>
                )}
              </div>

              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Created date range</p>
                <div className="flex items-center gap-2">
                  <input
                    type="date"
                    value={createdFrom}
                    onChange={(e) => setCreatedFrom(e.target.value)}
                    className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <span className="text-gray-600">—</span>
                  <input
                    type="date"
                    value={createdTo}
                    onChange={(e) => setCreatedTo(e.target.value)}
                    className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>
            </div>
          )}

          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Parse mode</p>
            <ParseModeSelector value={parseMode} onChange={setParseMode} />
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <p className="text-xs text-gray-500 uppercase tracking-wider">Message</p>
              <span className={`text-xs ${message.length > 3900 ? "text-red-400" : "text-gray-500"}`}>
                {message.length} / 4096
              </span>
            </div>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={4096}
              rows={6}
              placeholder="Your message to users…"
              className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 resize-y placeholder-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          {/* Media */}
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Media</p>
            <div className="flex items-center gap-3">
              <select
                value={mediaType}
                onChange={(e) => {
                  setMediaType(e.target.value as MediaKind);
                  setMediaFileId(null);
                  setMediaName("");
                }}
                className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="text">Text only</option>
                <option value="photo">Photo</option>
                <option value="document">Document</option>
              </select>
              {mediaType !== "text" && (
                <label className="px-3 py-1.5 bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-md cursor-pointer hover:text-white">
                  {uploading ? "Uploading…" : "Choose file"}
                  <input
                    type="file"
                    accept={mediaType === "photo" ? "image/*" : undefined}
                    className="hidden"
                    onChange={(e) => e.target.files?.[0] && handleUpload(e.target.files[0])}
                  />
                </label>
              )}
              {mediaFileId && <span className="text-xs text-green-400">✓ {mediaName || "uploaded"}</span>}
            </div>
          </div>

          {/* Delivery */}
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Delivery</p>
            <div className="flex gap-3 mb-2">
              {(["now", "schedule", "recurring"] as const).map((d) => (
                <label key={d} className="flex items-center gap-1.5 cursor-pointer text-sm text-gray-300 capitalize">
                  <input
                    type="radio"
                    name="delivery_mode"
                    checked={deliveryMode === d}
                    onChange={() => setDeliveryMode(d)}
                    className="accent-indigo-500"
                  />
                  {d === "now" ? "Send now" : d}
                </label>
              ))}
            </div>
            {deliveryMode === "schedule" && (
              <input
                type="datetime-local"
                value={scheduledFor}
                onChange={(e) => setScheduledFor(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            )}
            {deliveryMode === "recurring" && (
              <div className="flex flex-wrap items-center gap-2 text-sm text-gray-300">
                <span>Every</span>
                <input
                  type="number"
                  min={1}
                  value={interval}
                  onChange={(e) => setIntervalVal(Math.max(1, Number(e.target.value)))}
                  className="w-16 bg-gray-800 border border-gray-700 text-white rounded-md px-2 py-1"
                />
                <select
                  value={frequency}
                  onChange={(e) => setFrequency(e.target.value as "daily" | "weekly" | "monthly")}
                  className="bg-gray-800 border border-gray-700 text-white rounded-md px-2 py-1"
                >
                  <option value="daily">day(s)</option>
                  <option value="weekly">week(s)</option>
                  <option value="monthly">month(s)</option>
                </select>
                {frequency === "weekly" && (
                  <select
                    value={dayOfWeek}
                    onChange={(e) => setDayOfWeek(Number(e.target.value))}
                    className="bg-gray-800 border border-gray-700 text-white rounded-md px-2 py-1"
                  >
                    {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d, i) => (
                      <option key={i} value={i}>{d}</option>
                    ))}
                  </select>
                )}
                {frequency === "monthly" && (
                  <>
                    <span>on day</span>
                    <input
                      type="number"
                      min={1}
                      max={31}
                      value={dayOfMonth}
                      onChange={(e) => setDayOfMonth(Math.min(31, Math.max(1, Number(e.target.value))))}
                      className="w-16 bg-gray-800 border border-gray-700 text-white rounded-md px-2 py-1"
                    />
                  </>
                )}
                <span>at</span>
                <input
                  type="time"
                  value={timeOfDay}
                  onChange={(e) => setTimeOfDay(e.target.value)}
                  className="bg-gray-800 border border-gray-700 text-white rounded-md px-2 py-1"
                />
                <span className="text-xs text-gray-500">
                  {timeOfDay ? "" : "(defaults to current time)"}
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => previewMutation.mutate()}
              disabled={previewMutation.isPending}
              className="px-4 py-2 bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg hover:text-white disabled:opacity-50 transition-colors"
            >
              {previewMutation.isPending ? "Loading…" : "Preview Audience"}
            </button>
            <button
              onClick={() => saveDraftMutation.mutate()}
              disabled={saveDraftMutation.isPending}
              className="px-4 py-2 bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg hover:text-white disabled:opacity-50 transition-colors"
            >
              Save Draft
            </button>
            <button
              onClick={() => saveTemplateMut.mutate()}
              disabled={saveTemplateMut.isPending}
              className="px-4 py-2 bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-lg hover:text-white disabled:opacity-50 transition-colors"
            >
              Save as Template
            </button>
            <button
              onClick={handleSendClick}
              disabled={createMutation.isPending || previewMutation.isPending}
              className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {primaryLabel}
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Audience preview</p>
            {preview ? (
              <div className="grid grid-cols-2 gap-3">
                <Metric label="Matching Users" value={preview.count} />
                <Metric label="Average Score" value={preview.avg_score} tone="text-indigo-300" />
                <Metric label="With Username" value={preview.with_username} tone="text-green-400" />
                <Metric label="Without Username" value={preview.without_username} tone="text-amber-400" />
              </div>
            ) : (
              <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 text-sm text-gray-600">
                Click “Preview Audience” to see who matches.
              </div>
            )}
          </div>

          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Message preview</p>
            <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 min-h-[120px] text-sm text-gray-300 whitespace-pre-wrap break-words">
              {message || <span className="text-gray-600">Preview appears here…</span>}
            </div>
          </div>

          {activeBroadcastId && <ProgressPanel broadcastId={activeBroadcastId} />}
        </div>
      </div>

      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-md w-full mx-4 space-y-4">
            <h3 className="text-base font-semibold text-white">Confirm broadcast</h3>
            <p className="text-sm text-gray-300">
              You are about to send this message to{" "}
              <span className="font-semibold text-white">{confirmCount}</span> user
              {confirmCount !== 1 ? "s" : ""}. Continue?
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmOpen(false)}
                disabled={createMutation.isPending}
                className="px-4 py-2 bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg hover:text-white disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmSend}
                disabled={createMutation.isPending}
                className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                {createMutation.isPending ? "Sending…" : "Continue"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Recurring tab ────────────────────────────────────────────────────────────

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function describeRule(r: RecurringRule): string {
  const every = r.interval > 1 ? `every ${r.interval} ` : "every ";
  let unit: string;
  if (r.frequency === "daily") unit = r.interval > 1 ? "days" : "day";
  else if (r.frequency === "weekly")
    unit = `${r.interval > 1 ? "weeks" : "week"} on ${WEEKDAYS[r.day_of_week ?? 0]}`;
  else unit = `${r.interval > 1 ? "months" : "month"} on day ${r.day_of_month ?? 1}`;
  return `${every}${unit} at ${r.time_of_day}`;
}

function RecurringTab() {
  const queryClient = useQueryClient();
  const { data: rules = [], isLoading } = useQuery({
    queryKey: ["admin", "recurring-rules"],
    queryFn: getRecurringRules,
    refetchInterval: 30_000,
  });

  const deactivateMut = useMutation({
    mutationFn: (id: string) => deactivateRecurringRule(id),
    onSuccess: () => {
      toast.success("Recurring rule stopped");
      queryClient.invalidateQueries({ queryKey: ["admin", "recurring-rules"] });
    },
    onError: () => toast.error("Failed to stop rule"),
  });

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-4">
      <div>
        <h2 className="text-white font-medium">Recurring broadcasts</h2>
        <p className="text-xs text-gray-500 mt-1">
          Each rule fires a fresh broadcast on its schedule. Stopping a rule prevents future runs;
          past runs remain in History.
        </p>
      </div>

      {isLoading ? (
        <p className="text-gray-500 text-sm">Loading…</p>
      ) : rules.length === 0 ? (
        <p className="text-gray-500 text-sm">No recurring rules yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 border-b border-gray-800">
                <th className="py-2 pr-4 font-medium">Message</th>
                <th className="py-2 pr-4 font-medium">Audience</th>
                <th className="py-2 pr-4 font-medium">Schedule</th>
                <th className="py-2 pr-4 font-medium">Next run</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id} className="border-b border-gray-800/60 text-gray-300">
                  <td className="py-2 pr-4 max-w-[16rem]">
                    <span className="truncate inline-block max-w-full align-middle">
                      {r.media_type !== "text" && (
                        <span className="text-indigo-400 mr-1">[{r.media_type}]</span>
                      )}
                      {r.message_preview || <span className="text-gray-600">—</span>}
                    </span>
                  </td>
                  <td className="py-2 pr-4 whitespace-nowrap">
                    {AUDIENCE_LABELS[r.audience_type] ?? r.audience_type}
                  </td>
                  <td className="py-2 pr-4 whitespace-nowrap">{describeRule(r)}</td>
                  <td className="py-2 pr-4 whitespace-nowrap text-gray-400">
                    {r.is_active ? new Date(r.next_run_at).toLocaleString() : "—"}
                  </td>
                  <td className="py-2 pr-4">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        r.is_active
                          ? "bg-green-900/60 text-green-400"
                          : "bg-gray-800 text-gray-500"
                      }`}
                    >
                      {r.is_active ? "Active" : "Stopped"}
                    </span>
                  </td>
                  <td className="py-2 text-right">
                    {r.is_active && (
                      <button
                        onClick={() => {
                          if (confirm("Stop this recurring broadcast? Future runs will not fire.")) {
                            deactivateMut.mutate(r.id);
                          }
                        }}
                        disabled={deactivateMut.isPending}
                        className="text-red-400 hover:text-red-300 text-xs disabled:opacity-50"
                      >
                        Stop
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── History tab ──────────────────────────────────────────────────────────────

function HistoryTab() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<UserBroadcastHistoryItem | null>(null);

  const { data } = useQuery({
    queryKey: ["admin", "user-broadcasts", page],
    queryFn: () => getUserBroadcasts({ page, page_size: 50 }),
    refetchInterval: 5000,
  });

  const sendDraftMut = useMutation({
    mutationFn: (id: string) => sendDraft(id),
    onSuccess: () => {
      toast.success("Draft sent");
      setSelected(null);
      queryClient.invalidateQueries({ queryKey: ["admin", "user-broadcasts"] });
    },
    onError: () => toast.error("Failed to send draft"),
  });

  return (
    <div className="space-y-4">
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800 text-gray-500 text-xs">
            <tr>
              <th className="px-4 py-2 text-left">Created At</th>
              <th className="px-4 py-2 text-left">Audience</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Media</th>
              <th className="px-4 py-2 text-left">Scheduled</th>
              <th className="px-4 py-2 text-right">Recipients</th>
              <th className="px-4 py-2 text-right">Success</th>
              <th className="px-4 py-2 text-right">Failed</th>
              <th className="px-4 py-2 text-right">Blocked</th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-6 text-center text-gray-600 text-sm">
                  No user broadcasts yet
                </td>
              </tr>
            ) : (
              (data?.items ?? []).map((b) => (
                <tr
                  key={b.id}
                  onClick={() => setSelected(b)}
                  className="border-t border-gray-800 cursor-pointer hover:bg-gray-800/50"
                >
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {new Date(b.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 text-gray-300">{AUDIENCE_LABELS[b.audience_type] ?? b.audience_type}</td>
                  <td className="px-4 py-2"><BroadcastStatusBadge status={b.status} /></td>
                  <td className="px-4 py-2 text-gray-400 text-xs capitalize">{b.media_type}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {b.scheduled_for ? new Date(b.scheduled_for).toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-gray-300">{b.total_recipients}</td>
                  <td className="px-4 py-2 text-right text-green-400">{b.success_count}</td>
                  <td className="px-4 py-2 text-right text-red-400">{b.failed_count}</td>
                  <td className="px-4 py-2 text-right text-amber-400">{b.blocked_count}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {(data?.pages ?? 1) > 1 && (
        <div className="flex gap-2 justify-end text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-md text-gray-400 hover:text-white disabled:opacity-40"
          >
            ← Prev
          </button>
          <span className="px-2 py-1.5 text-gray-500">{page} / {data?.pages}</span>
          <button
            onClick={() => setPage((p) => Math.min(data!.pages, p + 1))}
            disabled={page >= (data?.pages ?? 1)}
            className="px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-md text-gray-400 hover:text-white disabled:opacity-40"
          >
            Next →
          </button>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={() => setSelected(null)}>
          <div
            className="w-full max-w-md bg-gray-900 border-l border-gray-800 h-full p-6 space-y-5 overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-white">Broadcast details</h3>
              <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white text-sm">
                ✕
              </button>
            </div>

            <dl className="space-y-2 text-sm">
              <Row label="Audience" value={AUDIENCE_LABELS[selected.audience_type] ?? selected.audience_type} />
              <Row label="Status" value={<BroadcastStatusBadge status={selected.status} />} />
              <Row label="Media" value={<span className="capitalize">{selected.media_type}</span>} />
              <Row
                label="Scheduled"
                value={selected.scheduled_for ? new Date(selected.scheduled_for).toLocaleString() : "—"}
              />
              <Row label="Template used" value={selected.template_id ? "Yes" : "—"} />
              <Row label="Created" value={new Date(selected.created_at).toLocaleString()} />
              <Row
                label="Completed"
                value={selected.completed_at ? new Date(selected.completed_at).toLocaleString() : "—"}
              />
            </dl>

            {selected.status === "draft" && (
              <button
                onClick={() => sendDraftMut.mutate(selected.id)}
                disabled={sendDraftMut.isPending}
                className="w-full px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              >
                {sendDraftMut.isPending ? "Sending…" : "Send now"}
              </button>
            )}

            <div className="grid grid-cols-4 gap-3 text-center">
              <Metric label="Total" value={selected.total_recipients} />
              <Metric label="Sent" value={selected.success_count} tone="text-green-400" />
              <Metric label="Failed" value={selected.failed_count} tone="text-red-400" />
              <Metric label="Blocked" value={selected.blocked_count} tone="text-amber-400" />
            </div>

            {(selected.status === "pending" || selected.status === "processing") && (
              <ProgressPanel broadcastId={selected.id} />
            )}

            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Message</p>
              <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm text-gray-300 whitespace-pre-wrap break-words">
                {selected.message}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-gray-500">{label}</dt>
      <dd className="text-gray-200 text-right">{value}</dd>
    </div>
  );
}

// ── Templates tab ──────────────────────────────────────────────────────────────

function TemplatesTab({ onUse }: { onUse: (t: BroadcastTemplate) => void }) {
  const queryClient = useQueryClient();
  const { data: templates = [] } = useQuery({
    queryKey: ["admin", "templates"],
    queryFn: getTemplates,
  });

  const empty: TemplateInput = {
    name: "",
    description: "",
    message: "",
    parse_mode: "HTML",
    media_type: "text",
    media_file_id: null,
  };
  const [form, setForm] = useState<TemplateInput>(empty);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [mediaName, setMediaName] = useState("");

  function reset() {
    setForm(empty);
    setEditingId(null);
    setMediaName("");
  }

  const saveMut = useMutation({
    mutationFn: () => (editingId ? updateTemplate(editingId, form) : createTemplate(form)),
    onSuccess: () => {
      toast.success(editingId ? "Template updated" : "Template created");
      queryClient.invalidateQueries({ queryKey: ["admin", "templates"] });
      reset();
    },
    onError: () => toast.error("Failed to save template"),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deleteTemplate(id),
    onSuccess: () => {
      toast.success("Template deleted");
      queryClient.invalidateQueries({ queryKey: ["admin", "templates"] });
    },
    onError: () => toast.error("Failed to delete template"),
  });

  async function upload(file: File) {
    if (form.media_type === "text") return;
    setUploading(true);
    try {
      const r = await uploadMedia(file, form.media_type as "photo" | "document");
      setForm({ ...form, media_file_id: r.media_file_id });
      setMediaName(file.name);
      toast.success("Media uploaded");
    } catch {
      toast.error("Upload failed");
    } finally {
      setUploading(false);
    }
  }

  function save() {
    if (!form.name.trim() || !form.message.trim()) return toast.error("Name and message are required");
    if (form.media_type !== "text" && !form.media_file_id) return toast.error("Upload a file first");
    saveMut.mutate();
  }

  function edit(t: BroadcastTemplate) {
    setEditingId(t.id);
    setForm({
      name: t.name,
      description: t.description ?? "",
      message: t.message,
      parse_mode: t.parse_mode,
      media_type: t.media_type,
      media_file_id: t.media_file_id,
    });
    setMediaName(t.media_file_id ? "existing media" : "");
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Editor */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 space-y-3">
        <h2 className="text-sm font-medium text-white">{editingId ? "Edit template" : "New template"}</h2>
        <input
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Name"
          className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2"
        />
        <input
          value={form.description ?? ""}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Description (optional)"
          className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2"
        />
        <div className="flex gap-3">
          <ParseModeSelector value={form.parse_mode as ParseMode} onChange={(m) => setForm({ ...form, parse_mode: m })} />
        </div>
        <textarea
          value={form.message}
          onChange={(e) => setForm({ ...form, message: e.target.value })}
          rows={5}
          placeholder="Message…"
          maxLength={4096}
          className="w-full bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-2 resize-y"
        />
        <div className="flex items-center gap-3">
          <select
            value={form.media_type}
            onChange={(e) => setForm({ ...form, media_type: e.target.value as MediaKind, media_file_id: null })}
            className="bg-gray-800 border border-gray-700 text-white text-sm rounded-md px-3 py-1.5"
          >
            <option value="text">Text only</option>
            <option value="photo">Photo</option>
            <option value="document">Document</option>
          </select>
          {form.media_type !== "text" && (
            <label className="px-3 py-1.5 bg-gray-800 border border-gray-700 text-gray-200 text-sm rounded-md cursor-pointer hover:text-white">
              {uploading ? "Uploading…" : "Choose file"}
              <input type="file" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            </label>
          )}
          {form.media_file_id && <span className="text-xs text-green-400">✓ {mediaName}</span>}
        </div>
        <div className="flex gap-3">
          <button
            onClick={save}
            disabled={saveMut.isPending}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            {editingId ? "Update" : "Create"}
          </button>
          {editingId && (
            <button onClick={reset} className="px-4 py-2 bg-gray-800 border border-gray-700 text-gray-300 text-sm rounded-lg hover:text-white">
              Cancel
            </button>
          )}
        </div>
      </div>

      {/* List */}
      <div className="space-y-3">
        {templates.length === 0 ? (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 text-sm text-gray-600">
            No templates yet.
          </div>
        ) : (
          templates.map((t) => (
            <div key={t.id} className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-white">{t.name}</span>
                <span className="text-xs text-gray-500 capitalize">{t.media_type}</span>
              </div>
              {t.description && <p className="text-xs text-gray-500">{t.description}</p>}
              <p className="text-xs text-gray-400 line-clamp-2 whitespace-pre-wrap">{t.message}</p>
              <div className="flex gap-3 text-xs">
                <button onClick={() => onUse(t)} className="text-indigo-400 hover:text-indigo-300">Use in broadcast</button>
                <button onClick={() => edit(t)} className="text-gray-400 hover:text-white">Edit</button>
                <button
                  onClick={() => confirm(`Delete template “${t.name}”?`) && delMut.mutate(t.id)}
                  className="text-red-400 hover:text-red-300"
                >
                  Delete
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export default function BroadcastPage() {
  const [tab, setTab] = useState<Tab>("channels");
  const [prefillTemplate, setPrefillTemplate] = useState<BroadcastTemplate | null>(null);

  const { data: channels = [] } = useQuery({
    queryKey: ["admin", "channels"],
    queryFn: getChannels,
    staleTime: 10 * 60 * 1000,
  });

  const activeChannels = channels.filter((c) => c.is_active);

  const tabs: { key: Tab; label: string }[] = [
    { key: "channels", label: "Channels" },
    { key: "users", label: "Users" },
    { key: "templates", label: "Templates" },
    { key: "recurring", label: "Recurring" },
    { key: "history", label: "History" },
  ];

  function useTemplate(t: BroadcastTemplate) {
    setPrefillTemplate(t);
    setTab("users");
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <h1 className="text-xl font-semibold text-white">Broadcast</h1>

      <div className="flex rounded-lg overflow-hidden border border-gray-700 text-sm w-fit">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-5 py-2 transition-colors ${
              tab === t.key ? "bg-indigo-600 text-white" : "bg-gray-800 text-gray-400 hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "channels" && <ChannelsTab channels={activeChannels} />}
      {tab === "users" && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <UsersTab
            prefillTemplate={prefillTemplate}
            clearPrefill={() => setPrefillTemplate(null)}
          />
        </div>
      )}
      {tab === "templates" && <TemplatesTab onUse={useTemplate} />}
      {tab === "recurring" && <RecurringTab />}
      {tab === "history" && <HistoryTab />}
    </div>
  );
}
