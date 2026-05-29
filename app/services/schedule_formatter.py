from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytz
from jinja2 import Environment, FileSystemLoader

from app.core.config import settings
from app.db.models.channel import Channel
from app.db.models.reservation import Reservation
from app.db.models.schedule_event import ScheduleEvent

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
TZ = pytz.timezone(settings.TIMEZONE)

_CLOCK_EMOJI: dict[tuple[int, int], str] = {
    (1, 0): "🕐",  (1, 30): "🕜",
    (2, 0): "🕑",  (2, 30): "🕝",
    (3, 0): "🕒",  (3, 30): "🕞",
    (4, 0): "🕓",  (4, 30): "🕟",
    (5, 0): "🕔",  (5, 30): "🕠",
    (6, 0): "🕕",  (6, 30): "🕡",
    (7, 0): "🕖",  (7, 30): "🕢",
    (8, 0): "🕗",  (8, 30): "🕣",
    (9, 0): "🕘",  (9, 30): "🕤",
    (10, 0): "🕙", (10, 30): "🕥",
    (11, 0): "🕚", (11, 30): "🕦",
    (12, 0): "🕛", (12, 30): "🕧",
}

_GENDER_EMOJI: dict[str | None, str] = {
    "male": "👨‍💼",
    "female": "👩‍💼",
    "not_say": "🧑‍💼",
    None: "🧑‍💼",
}


def clock_emoji_for(dt: datetime) -> str:
    hour_12 = dt.hour % 12 or 12
    return _CLOCK_EMOJI.get((hour_12, dt.minute), "⏰")


def format_time(dt: datetime) -> str:
    hour_12 = dt.hour % 12 or 12
    period = "AM" if dt.hour < 12 else "PM"
    return f"{hour_12}:{dt.minute:02d} {period}"


@dataclass
class ReservationEntry:
    clock: str
    time: str
    gender_emoji: str
    country_display: str
    user_code: str
    score: int


@dataclass
class EventEntry:
    title: str


class ScheduleFormatter:
    """Renders a daily schedule message using a Jinja2 template.

    Keeps all formatting logic in one place so the template stays
    declarative and the business rules stay in Python.
    """

    def __init__(self) -> None:
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._template = env.get_template("schedule_message.j2")

    def render(
        self,
        channel: Channel,
        target_date: date,
        reservations: list[Reservation],
        events: list[ScheduleEvent],
    ) -> str:
        entries = [self._build_entry(r) for r in reservations]
        event_entries = [EventEntry(title=e.title) for e in events]
        date_str = target_date.strftime(f"%A, %B {target_date.day}, %Y")

        return self._template.render(
            channel_name=channel.name,
            invite_link=channel.invite_link,
            date_str=date_str,
            entries=entries,
            events=event_entries,
        )

    def _build_entry(self, reservation: Reservation) -> ReservationEntry:
        user = reservation.user
        slot_local = reservation.slot.slot_datetime.astimezone(TZ)

        country = user.country_rel
        if country:
            flag = country.flag_emoji or ""
            country_display = f"{flag} {country.name}".strip() if flag else country.name
        else:
            country_display = "—"

        return ReservationEntry(
            clock=clock_emoji_for(slot_local),
            time=format_time(slot_local),
            gender_emoji=_GENDER_EMOJI.get(user.gender, "🧑‍💼"),
            country_display=country_display,
            user_code=user.public_user_code,
            score=user.participation_score,
        )
