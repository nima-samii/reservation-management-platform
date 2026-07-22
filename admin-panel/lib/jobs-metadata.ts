export interface JobMetadata {
  name: string;
  description: string;
  schedule: string;
}

/**
 * Friendly display metadata for the recurring scheduler jobs surfaced on the
 * admin Jobs page. Keyed by APScheduler job id (app/schedulers/setup.py).
 * Jobs not listed here (e.g. one-off per-entity delivery jobs like
 * `user_broadcast:<uuid>`) are treated as internal/technical and excluded
 * from the main table.
 */
export const JOB_METADATA: Record<string, JobMetadata> = {
  slot_generation: {
    name: "Generate Booking Slots",
    description:
      "Creates available reservation time slots for the next 14 days so users can book sessions in advance.",
    schedule: "Every day at 00:00 and 06:00",
  },
  reservation_lifecycle: {
    name: "Close Finished Sessions",
    description:
      "Marks reservations as completed once their scheduled session time has passed.",
    schedule: "Every 30 minutes",
  },
  same_day_reminders: {
    name: "Send Today's Reminders",
    description:
      "Sends a Telegram message to every user who has a session scheduled today.",
    schedule: "Once daily (admin-configured time)",
  },
  pre_session_reminders: {
    name: "Send “Starting Soon” Reminders",
    description:
      "Sends a Telegram message to users about 30 minutes before their session begins.",
    schedule: "Every 5 minutes",
  },
  final_reminders: {
    name: "Send Final Live Reminders",
    description:
      "Sends a final “join now” message a few minutes before each session starts, guiding the user into the live channel.",
    schedule: "Every minute",
  },
  daily_broadcast: {
    name: "Post Daily Schedule",
    description:
      "Posts and pins today's session schedule to each active Telegram channel.",
    schedule: "Once daily (admin-configured time)",
  },
  recurring_broadcast_dispatch: {
    name: "Dispatch Scheduled Broadcasts",
    description:
      "Checks for admin-configured recurring broadcast rules that are due and sends them.",
    schedule: "Every minute",
  },
  inactivity_reminders: {
    name: "Remind Inactive Users",
    description:
      "Sends a Telegram message to users who haven't booked a session in a while, encouraging them to come back.",
    schedule: "Once daily (admin-configured time)",
  },
};
