from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    output_dir: str = ""
    dark_mode: bool = False


def load_settings() -> AppSettings:
    path = _settings_path()
    if not path.exists():
        return AppSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return AppSettings()

    return AppSettings(
        output_dir=str(data.get("output_dir") or ""),
        dark_mode=bool(data.get("dark_mode", False)),
    )


def save_settings(settings: AppSettings) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "output_dir": settings.output_dir,
        "dark_mode": settings.dark_mode,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _settings_path() -> Path:
    if platform.system() == "Windows":
        appdata = Path.home() / "AppData" / "Roaming"
        return appdata / "Pobieracz-yt-dlp" / "settings.json"
    return Path.home() / ".config" / "pobieracz-yt-dlp" / "settings.json"
