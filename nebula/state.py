from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from nebula.schedule import MSK

ROOT = Path(__file__).resolve().parent.parent


def _path() -> Path:
    return Path(os.environ.get("STATE_PATH", ROOT / "data" / "state.json"))


@dataclass
class State:
    auto_shift: int = 0
    down_since: float | None = None
    chats: list[int] = field(default_factory=list)
    discord_channels: list[int] = field(default_factory=list)
    last_warn: str | None = None
    last_spawn: str | None = None
    last_portal: str | None = None

    def down_at(self) -> datetime | None:
        if self.down_since is None:
            return None
        return datetime.fromtimestamp(self.down_since, MSK)


def load() -> State:
    path = _path()
    if not path.exists():
        return State()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return State(
        auto_shift=int(raw.get("auto_shift", raw.get("hour_shift", 0))),
        down_since=raw.get("down_since"),
        chats=[int(x) for x in raw.get("chats", [])],
        discord_channels=[int(x) for x in raw.get("discord_channels", [])],
        last_warn=raw.get("last_warn") or raw.get("last_slot"),
        last_spawn=raw.get("last_spawn"),
        last_portal=raw.get("last_portal"),
    )


def save(state: State) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
