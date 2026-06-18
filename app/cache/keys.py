class CacheKey:
    """Centralised Redis key factory — all keys live here to prevent collisions."""

    # Slot-level distributed lock
    @staticmethod
    def slot_lock(slot_id: str) -> str:
        return f"lock:slot:{slot_id}"

    # Per-user rate limiting (sliding window)
    @staticmethod
    def rate_limit(telegram_id: int) -> str:
        return f"rl:user:{telegram_id}"

    # Anti-flood (last message timestamp)
    @staticmethod
    def anti_flood(telegram_id: int) -> str:
        return f"flood:user:{telegram_id}"

    # Country list cache
    @staticmethod
    def country_list() -> str:
        return "cache:countries:all"

    # Country search results
    @staticmethod
    def country_search(query: str) -> str:
        return f"cache:countries:search:{query.lower()}"

    # User object cache
    @staticmethod
    def user(telegram_id: int) -> str:
        return f"cache:user:{telegram_id}"

    # Mandatory-membership verification result (successful checks only).
    # `version` is a signature of the configured channel set, so changing the
    # required channels automatically invalidates every cached result.
    @staticmethod
    def membership(user_id: int, version: str) -> str:
        return f"membership:{version}:{user_id}"

    # Slot generation lock (prevents double-run)
    @staticmethod
    def slot_generation_lock() -> str:
        return "lock:slot_generation"

    # Reservation lifecycle lock (prevents double-run)
    @staticmethod
    def reservation_lifecycle_lock() -> str:
        return "lock:reservation_lifecycle"

    # Same-day reminder lock (runs once at noon)
    @staticmethod
    def same_day_reminder_lock() -> str:
        return "lock:reminder:same_day"

    # Pre-session reminder lock (runs every 5 minutes)
    @staticmethod
    def pre_session_reminder_lock() -> str:
        return "lock:reminder:pre_session"

    # Daily schedule broadcast lock (runs once at noon)
    @staticmethod
    def daily_broadcast_lock() -> str:
        return "lock:broadcast:daily"

    # Admin dashboard stats cache (TTL 60s)
    @staticmethod
    def admin_dashboard_stats() -> str:
        return "cache:admin:dashboard:stats"

    # Admin settings change history (Redis list, max 100 entries)
    @staticmethod
    def admin_settings_history() -> str:
        return "admin:settings:history"

    # Per-admin manual broadcast rate limit key
    @staticmethod
    def admin_broadcast_rate_limit(admin: str) -> str:
        return f"rl:admin:broadcast:{admin}"

    # Per-broadcast lock for the user-broadcast background worker
    @staticmethod
    def user_broadcast_lock(broadcast_id: str) -> str:
        return f"lock:broadcast:user:{broadcast_id}"

    # Recurring-broadcast dispatcher lock (runs every minute)
    @staticmethod
    def recurring_broadcast_lock() -> str:
        return "lock:broadcast:recurring_dispatch"
