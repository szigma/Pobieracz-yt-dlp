from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DownloadMode(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"


@dataclass(slots=True)
class FormatOption:
    id: str
    label: str
    selector: str
    availability_id: str
    ext: str
    height: Optional[int] = None
    note: str = ""
    requires_ffmpeg: bool = False


@dataclass(slots=True)
class DownloadTask:
    id: str
    url: str
    mode: DownloadMode
    output_dir: str = ""
    title: str = ""
    status: str = "Pending"
    progress: float = 0.0
    error_message: str = ""
    available_formats: list[FormatOption] = field(default_factory=list)
    selected_format: str = "auto"
    selected_format_label: str = "Auto"
    filename: str = ""
