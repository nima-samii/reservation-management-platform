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

    # Slot generation lock (prevents double-run)
    @staticmethod
    def slot_generation_lock() -> str:
        return "lock:slot_generation"

    # Reservation lifecycle lock (prevents double-run)
    @staticmethod
    def reservation_lifecycle_lock() -> str:
        return "lock:reservation_lifecycle"
