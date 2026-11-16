"""Круг Небулы.

Час задаёт локации. Сундук и руда встают трижды за этот час: :00, :20, :40.
Сдвиг техработ двигает только час локации. Минутная сетка остаётся на часах МСК.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

LOCS = ("Аркенум", "Орки", "Дырка", "Шрайн")
WARN_BEFORE = timedelta(minutes=5)
SPAWN_GRACE = timedelta(seconds=45)


def locations(hour: int) -> tuple[str, str]:
    """Руда на текущем шаге круга, сундук на предыдущем."""
    step = hour % 4
    ore = LOCS[step]
    chest = LOCS[(step + 3) % 4]
    return ore, chest


def game_hour(wall: datetime, shift: int) -> int:
    wall = wall.astimezone(MSK)
    return (wall.hour + shift) % 24


def missed_hour_ticks(down: datetime, up: datetime) -> int:
    """Сколько переходов XX:00 не случилось, пока мир лежал.

    Тик часа считается уже прошедшим, если down строго позже этой отметки.
    08:10 → 12:11 пропускает 09, 10, 11 и 12.
    """
    down = down.astimezone(MSK)
    up = up.astimezone(MSK)
    if up <= down:
        return 0
    cursor = down.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    missed = 0
    while cursor <= up:
        missed += 1
        cursor += timedelta(hours=1)
    return missed


def next_spawn(now: datetime) -> datetime:
    now = now.astimezone(MSK).replace(microsecond=0)
    slot = now.replace(second=0, minute=(now.minute // 20) * 20)
    if now >= slot:
        slot += timedelta(minutes=20)
    return slot


def portal(at: datetime) -> tuple[bool, datetime]:
    """Портал в Дырку: :00–:15 и :30–:45 открыт. Сетку не сдвигаем."""
    at = at.astimezone(MSK)
    quarter = at.minute // 15
    open_ = quarter % 2 == 0
    end_minute = (quarter + 1) * 15
    base = at.replace(second=0, microsecond=0)
    if end_minute == 60:
        until = base.replace(minute=0) + timedelta(hours=1)
    else:
        until = base.replace(minute=end_minute)
    return open_, until


def pending(now: datetime, last_warn: str | None, last_spawn: str | None) -> tuple[str, datetime] | None:
    """'warn' в окне T-5мин, 'spawn' в первые 45с после отметки."""
    now = now.astimezone(MSK)
    upcoming = next_spawn(now)
    for candidate in (upcoming - timedelta(minutes=20), upcoming):
        key = slot_key(candidate)
        if last_spawn != key and candidate <= now < candidate + SPAWN_GRACE:
            return "spawn", candidate
        warn_at = candidate - WARN_BEFORE
        if last_warn != key and warn_at <= now < candidate:
            return "warn", candidate
    return None


def next_portal_mark(now: datetime) -> datetime:
    now = now.astimezone(MSK).replace(microsecond=0)
    slot = now.replace(second=0, minute=(now.minute // 15) * 15)
    if now >= slot:
        slot += timedelta(minutes=15)
    return slot


def pending_portal(now: datetime, last_portal: str | None) -> datetime | None:
    """Переключение :00/:15/:30/:45, если уложились в 45с после отметки."""
    now = now.astimezone(MSK)
    upcoming = next_portal_mark(now)
    for candidate in (upcoming - timedelta(minutes=15), upcoming):
        if last_portal == slot_key(candidate):
            continue
        if candidate <= now < candidate + SPAWN_GRACE:
            return candidate
    return None


def seconds_until_next(
    now: datetime,
    last_warn: str | None,
    last_spawn: str | None,
    last_portal: str | None = None,
) -> float:
    now = now.astimezone(MSK)
    spawn = next_spawn(now)
    moments: list[datetime] = []
    for candidate in (spawn - timedelta(minutes=20), spawn, spawn + timedelta(minutes=20)):
        key = slot_key(candidate)
        if last_warn != key:
            moments.append(candidate - WARN_BEFORE)
        if last_spawn != key:
            moments.append(candidate)
    mark = next_portal_mark(now)
    for candidate in (mark - timedelta(minutes=15), mark, mark + timedelta(minutes=15)):
        if last_portal != slot_key(candidate):
            moments.append(candidate)
    future = [(m - now).total_seconds() for m in moments if m > now]
    if not future:
        return 20 * 60
    return min(future)


def slot_key(spawn: datetime) -> str:
    spawn = spawn.astimezone(MSK)
    return spawn.strftime("%Y-%m-%d %H:%M")


def _pair(spawn: datetime, shift: int) -> tuple[str, str, str]:
    spawn = spawn.astimezone(MSK)
    ore, chest = locations(game_hour(spawn, shift))
    extra = ""
    if chest == "Дырка" or ore == "Дырка":
        open_, until = portal(spawn)
        state = "открыт" if open_ else "закрыт"
        extra = f"\nпортал Дырки {state} до {until.strftime('%H:%M')}"
    return ore, chest, extra


def _in_minutes(left: int) -> str:
    n = abs(left) % 100
    if 11 <= n <= 14:
        return "минут"
    n = abs(left) % 10
    if n == 1:
        return "минуту"
    if 2 <= n <= 4:
        return "минуты"
    return "минут"


def preview_text(spawn: datetime, shift: int, now: datetime | None = None) -> str:
    ore, chest, extra = _pair(spawn, shift)
    spawn = spawn.astimezone(MSK)
    now = (now or spawn - WARN_BEFORE).astimezone(MSK)
    left = max(1, round((spawn - now).total_seconds() / 60))
    when = spawn.strftime("%H:%M")
    return f"Через {left} {_in_minutes(left)}, {when}\nсундук: {chest}\nруда: {ore}{extra}"


def spawned_text(spawn: datetime, shift: int) -> str:
    ore, chest, extra = _pair(spawn, shift)
    when = spawn.astimezone(MSK).strftime("%H:%M")
    return (
        f"{when}\n"
        f"Сундуки заспавнились: {chest}\n"
        f"Руда заспавнилась: {ore}{extra}"
    )


def portal_text(at: datetime) -> str:
    at = at.astimezone(MSK).replace(second=0, microsecond=0)
    open_, until = portal(at)
    verb = "открылся" if open_ else "закрылся"
    return f"{at.strftime('%H:%M')}\nПортал Дырки {verb} до {until.strftime('%H:%M')}"


def _selfcheck() -> None:
    assert locations(0) == ("Аркенум", "Шрайн")
    assert locations(1) == ("Орки", "Аркенум")
    assert locations(2) == ("Дырка", "Орки")
    assert locations(3) == ("Шрайн", "Дырка")
    assert locations(12) == ("Аркенум", "Шрайн")
    assert locations(13) == ("Орки", "Аркенум")

    down = datetime(2026, 11, 16, 8, 10, tzinfo=MSK)
    up = datetime(2026, 11, 16, 12, 11, tzinfo=MSK)
    assert missed_hour_ticks(down, up) == 4
    assert missed_hour_ticks(
        datetime(2026, 11, 16, 14, 50, tzinfo=MSK),
        datetime(2026, 11, 16, 15, 10, tzinfo=MSK),
    ) == 1
    assert missed_hour_ticks(
        datetime(2026, 11, 16, 8, 10, tzinfo=MSK),
        datetime(2026, 11, 16, 8, 50, tzinfo=MSK),
    ) == 0

    noon = datetime(2026, 11, 16, 12, 0, tzinfo=MSK)
    key = slot_key(noon)
    assert next_spawn(noon) == noon + timedelta(minutes=20)
    assert pending(noon - timedelta(minutes=5), None, None) == ("warn", noon)
    assert pending(noon - timedelta(minutes=2), key, None) is None
    assert pending(noon + timedelta(seconds=2), key, None) == ("spawn", noon)
    assert pending(noon + timedelta(seconds=2), key, key) is None
    assert seconds_until_next(noon - timedelta(minutes=6), None, None) == 60

    assert portal(noon) == (True, noon + timedelta(minutes=15))
    assert portal(noon + timedelta(minutes=15))[0] is False
    assert portal(noon + timedelta(minutes=30))[0] is True
    assert portal(noon + timedelta(minutes=45))[0] is False
    assert pending_portal(noon + timedelta(seconds=2), None) == noon
    assert pending_portal(noon + timedelta(seconds=2), key) is None
    assert pending_portal(noon + timedelta(seconds=50), None) is None
    assert portal_text(noon) == "12:00\nПортал Дырки открылся до 12:15"
    assert portal_text(noon + timedelta(minutes=15)) == "12:15\nПортал Дырки закрылся до 12:30"
    assert preview_text(noon, 0, noon - timedelta(minutes=5)).startswith("Через 5 минут, 12:00")
    assert preview_text(noon, 0, noon - timedelta(minutes=2)).startswith("Через 2 минуты, 12:00")
    print("schedule ok")


if __name__ == "__main__":
    _selfcheck()
