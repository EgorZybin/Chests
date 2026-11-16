"""Круг Небулы.

Час задаёт локации. Сундук и руда встают трижды за этот час: :00, :20, :40.
Сдвиг техработ двигает только час локации. Минутная сетка остаётся на часах МСК.
В 19:00 МСК сундук и руда на час берутся со следующего шага. В 20:00 показывается
пара, которая должна была стоять в 19:00. С 21:00 круг снова обычный.
Кроме воскресенья босс в 21:00 держит эту пару ещё и на 22:00. Шаг, который
должен был начаться в 22:00, пропускается, и в 23:00 круг уже обычный.
В ночь после босса круг с 00:00 до 19:00 идёт на час позади: 00:00 повторяет
пару 23:00, а в 01:00 выходит пара, которая должна была стоять в 00:00.
Дальше шаг за шагом, без прыжка на обычный час. После воскресенья, в
понедельник утром, повтора нет. Портал эти часы не сдвигает.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

LOCS = ("Аркейский лагерь", "Поселение орков", "Святилище печати", "Жертвенный храм")
WARN_BEFORE = timedelta(minutes=5)
SPAWN_GRACE = timedelta(seconds=45)
EVENT_HOUR = 19
BOSS_HOUR = 21


def locations(hour: int) -> tuple[str, str]:
    """Руда на текущем шаге круга, сундук на предыдущем."""
    step = hour % 4
    ore = LOCS[step]
    chest = LOCS[(step + 3) % 4]
    return ore, chest


def game_hour(wall: datetime, shift: int) -> int:
    wall = wall.astimezone(MSK)
    return (wall.hour + shift) % 24


def location_hour(wall: datetime, shift: int) -> int:
    """Час круга для сундука и руды.

    19:00–20:00 МСК показывает следующий шаг. 20:00–21:00 возвращает пару,
    пропущенную в 19:00. Кроме воскресенья 22:00 повторяет пару 21:00,
    шаг 22:00 пропускается. В 23:00 час снова равен игровому.
    В ночь после такого босса с 00:00 до 19:00 круг на час позади:
    00:00 повторяет 23:00, дальше каждый час — следующий шаг, без прыжка
    обратно на обычный час. В 19:00 снова эвент от обычного часа.
    """
    wall = wall.astimezone(MSK)
    hour = game_hour(wall, shift)
    if wall.hour == EVENT_HOUR:
        return (hour + 1) % 24
    if wall.hour == EVENT_HOUR + 1:
        return (hour - 1) % 24
    if wall.hour == BOSS_HOUR + 1 and wall.weekday() != 6:
        return (hour - 1) % 24
    if wall.hour < EVENT_HOUR and wall.weekday() != 0:
        return (hour - 1) % 24
    return hour


def placed(wall: datetime, shift: int) -> tuple[str, str]:
    return locations(location_hour(wall, shift))


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
    """Портал Святилища печати: :15–:30 и :45–:00 открыт. Сетку не сдвигаем."""
    at = at.astimezone(MSK)
    quarter = at.minute // 15
    open_ = quarter % 2 == 1
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


def _pair(spawn: datetime, shift: int) -> tuple[str, str]:
    return placed(spawn, shift)


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
    ore, chest = _pair(spawn, shift)
    spawn = spawn.astimezone(MSK)
    now = (now or spawn - WARN_BEFORE).astimezone(MSK)
    left = max(1, round((spawn - now).total_seconds() / 60))
    return f"Через {left} {_in_minutes(left)}\nСундук: {chest} · Руда: {ore}"


def spawned_text(spawn: datetime, shift: int) -> str:
    ore, chest = _pair(spawn, shift)
    return f"Сундук: {chest} · Руда: {ore}"


def portal_text(at: datetime) -> str:
    at = at.astimezone(MSK).replace(second=0, microsecond=0)
    open_, until = portal(at)
    verb = "открылся" if open_ else "закрылся"
    return f"Портал Святилища печати {verb} до {until.strftime('%H:%M')}"


def _selfcheck() -> None:
    assert locations(0) == ("Аркейский лагерь", "Жертвенный храм")
    assert locations(1) == ("Поселение орков", "Аркейский лагерь")
    assert locations(2) == ("Святилище печати", "Поселение орков")
    assert locations(3) == ("Жертвенный храм", "Святилище печати")
    assert locations(12) == ("Аркейский лагерь", "Жертвенный храм")
    assert locations(13) == ("Поселение орков", "Аркейский лагерь")

    day = datetime(2026, 11, 16, tzinfo=MSK)
    at19 = day.replace(hour=19)
    at20 = day.replace(hour=20)
    assert placed(day.replace(hour=18, minute=40), 0) == locations(18)
    assert placed(at19, 0) == locations(20)
    assert placed(at19.replace(minute=40), 0) == locations(20)
    assert placed(at20, 0) == locations(19)
    assert placed(day.replace(hour=21), 0) == locations(21)
    assert placed(at19, -2) == locations(18)
    assert placed(at20, -2) == ("Поселение орков", "Аркейский лагерь")
    boss = ("Жертвенный храм", "Святилище печати")
    assert day.weekday() == 0
    assert placed(day.replace(hour=21), -2) == boss
    assert placed(day.replace(hour=22), -2) == boss
    assert placed(day.replace(hour=22, minute=40), -2) == boss
    assert placed(day.replace(hour=23), -2) == ("Поселение орков", "Аркейский лагерь")
    night = datetime(2026, 11, 17, tzinfo=MSK)
    assert night.weekday() == 1
    late = ("Поселение орков", "Аркейский лагерь")
    assert placed(night.replace(hour=0, minute=20), -2) == late
    assert placed(night.replace(hour=0, minute=40), -2) == late
    assert placed(night.replace(hour=1), -2) == ("Святилище печати", "Поселение орков")
    assert placed(night.replace(hour=2), -2) == boss
    assert placed(night.replace(hour=2, minute=40), -2) == boss
    assert placed(night.replace(hour=3), -2) == locations(0)
    assert placed(day.replace(hour=0), -2) == ("Святилище печати", "Поселение орков")
    sunday = datetime(2026, 11, 22, 22, tzinfo=MSK)
    assert sunday.weekday() == 6
    assert placed(sunday, -2) == ("Аркейский лагерь", "Жертвенный храм")
    assert placed(sunday.replace(hour=0), -2) == late
    assert portal(at19)[0] is False

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

    assert portal(noon) == (False, noon + timedelta(minutes=15))
    assert portal(noon + timedelta(minutes=15))[0] is True
    assert portal(noon + timedelta(minutes=30))[0] is False
    assert portal(noon + timedelta(minutes=45))[0] is True
    assert pending_portal(noon + timedelta(seconds=2), None) == noon
    assert pending_portal(noon + timedelta(seconds=2), key) is None
    assert pending_portal(noon + timedelta(seconds=50), None) is None
    assert portal_text(noon) == "Портал Святилища печати закрылся до 12:15"
    assert portal_text(noon + timedelta(minutes=15)) == "Портал Святилища печати открылся до 12:30"
    assert portal_text(noon + timedelta(minutes=30)) == "Портал Святилища печати закрылся до 12:45"
    assert preview_text(noon, 0, noon - timedelta(minutes=5)).startswith("Через 5 минут\n")
    assert preview_text(noon, 0, noon - timedelta(minutes=2)).startswith("Через 2 минуты\n")
    print("schedule ok")


if __name__ == "__main__":
    _selfcheck()
