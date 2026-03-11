from __future__ import annotations

import copy
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable, Iterable, Optional

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .models import DownloadMode, DownloadTask, FormatOption

TaskCallback = Callable[[DownloadTask], None]


def parse_urls(raw_text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for line in raw_text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


class DownloaderService:
    def __init__(self) -> None:
        self._tasks: dict[str, DownloadTask] = {}
        self._cancel_event = threading.Event()
        self._ffmpeg_available = self._detect_ffmpeg_available()

    def analyze_urls(
        self,
        urls: Iterable[str],
        mode: DownloadMode,
        on_task_update: Optional[TaskCallback] = None,
    ) -> list[DownloadTask]:
        tasks: list[DownloadTask] = []
        for url in urls:
            task = DownloadTask(id=str(uuid.uuid4()), url=url, mode=mode, status="Analyzing")
            self._tasks[task.id] = task
            self._emit(on_task_update, task)
            try:
                info = self._extract_info(url)
                task.title = info.get("title") or url
                task.status = "Ready"
                task.error_message = ""
                if mode == DownloadMode.VIDEO:
                    task.available_formats = self._build_video_formats(info)
                    task.selected_format = "auto"
                    task.selected_format_label = "Auto"
                else:
                    task.available_formats = []
                    task.selected_format = "audio"
                    task.selected_format_label = "MP3"
            except Exception as exc:  # noqa: BLE001
                task.status = "Error"
                task.error_message = str(exc)
                task.title = url
            tasks.append(copy.deepcopy(task))
            self._emit(on_task_update, task)
        return tasks

    def set_selected_format(self, task_id: str, format_id: str) -> DownloadTask:
        task = self._tasks[task_id]
        if task.mode != DownloadMode.VIDEO:
            task.selected_format = "audio"
            task.selected_format_label = "MP3"
            return copy.deepcopy(task)

        if format_id == "auto":
            task.selected_format = "auto"
            task.selected_format_label = "Auto"
            return copy.deepcopy(task)

        selected = next((item for item in task.available_formats if item.id == format_id), None)
        if selected is None:
            raise ValueError("Wybrana jakość nie jest dostępna dla tego filmu.")

        task.selected_format = selected.id
        task.selected_format_label = selected.label
        return copy.deepcopy(task)

    def start_queue(
        self,
        tasks: Iterable[DownloadTask],
        output_dir: str,
        on_task_update: Optional[TaskCallback] = None,
    ) -> None:
        self._cancel_event.clear()
        output_path = Path(output_dir).expanduser()
        output_path.mkdir(parents=True, exist_ok=True)

        for queued_task in tasks:
            if self._cancel_event.is_set():
                break

            task = self._tasks.get(queued_task.id)
            if task is None:
                continue

            task.output_dir = str(output_path)
            task.progress = 0.0
            task.error_message = ""
            task.status = "Downloading"
            self._emit(on_task_update, task)

            try:
                self._ffmpeg_available = self._detect_ffmpeg_available()
                if task.mode == DownloadMode.AUDIO and not self._ffmpeg_available:
                    raise RuntimeError("Tryb MP3 wymaga zainstalowanego ffmpeg w zmiennej PATH.")

                info = self._extract_info(task.url)
                if task.mode == DownloadMode.VIDEO and task.selected_format != "auto":
                    self._ensure_selected_format_available(task, info)
                    selected = next((item for item in task.available_formats if item.id == task.selected_format), None)
                    if selected is not None and selected.requires_ffmpeg and not self._ffmpeg_available:
                        raise RuntimeError(
                            "Wybrana jakość wymaga ffmpeg do połączenia osobnego obrazu i dźwięku. "
                            "Zainstaluj ffmpeg albo wybierz format z dźwiękiem w jednym pliku."
                        )

                self._download_task(task, output_path, on_task_update)
                if self._cancel_event.is_set():
                    task.status = "Cancelled"
                else:
                    task.status = "Done"
                    task.progress = 100.0
            except Exception as exc:  # noqa: BLE001
                task.status = "Error"
                task.error_message = str(exc)
            self._emit(on_task_update, task)

    def cancel_current(self) -> None:
        self._cancel_event.set()

    def _download_task(
        self,
        task: DownloadTask,
        output_path: Path,
        on_task_update: Optional[TaskCallback],
    ) -> None:
        outtmpl = str(output_path / "%(title)s [%(id)s].%(ext)s")
        options = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._build_progress_hook(task, on_task_update)],
        }

        if task.mode == DownloadMode.AUDIO:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        else:
            selector = self._resolve_format_selector(task)
            options["format"] = selector
            if self._ffmpeg_available:
                options["merge_output_format"] = "mp4"

        with YoutubeDL(options) as ydl:
            ydl.download([task.url])

    def _resolve_format_selector(self, task: DownloadTask) -> str:
        if task.selected_format == "auto":
            if not self._ffmpeg_available:
                return "best[ext=mp4][acodec!=none]/best[acodec!=none]/best"
            return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"

        selected = next((item for item in task.available_formats if item.id == task.selected_format), None)
        if selected is None:
            raise RuntimeError("Wybrana jakość nie jest już dostępna w pamięci aplikacji.")
        return selected.selector

    def _ensure_selected_format_available(self, task: DownloadTask, info: dict) -> None:
        current_ids = {str(fmt.get("format_id")) for fmt in info.get("formats", []) if fmt.get("format_id")}
        selected = next((item for item in task.available_formats if item.id == task.selected_format), None)
        if selected is None or selected.availability_id not in current_ids:
            raise RuntimeError("Wybrana jakość nie jest już dostępna dla tego filmu.")

    def _extract_info(self, url: str) -> dict:
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
        }
        try:
            with YoutubeDL(options) as ydl:
                return ydl.extract_info(url, download=False)
        except DownloadError as exc:
            raise RuntimeError(str(exc)) from exc

    def _build_video_formats(self, info: dict) -> list[FormatOption]:
        formats = info.get("formats") or []
        best_per_label: dict[str, FormatOption] = {}

        for fmt in formats:
            format_id = fmt.get("format_id")
            ext = (fmt.get("ext") or "").lower()
            vcodec = fmt.get("vcodec")
            if not format_id or vcodec in (None, "none"):
                continue
            if ext and ext != "mp4":
                continue

            height = fmt.get("height")
            if not height:
                continue

            has_audio = fmt.get("acodec") not in (None, "none")
            note = "video+audio" if has_audio else "video + best audio"
            base_label = f"{height}p mp4"
            label = base_label if has_audio else f"{base_label} (wymaga ffmpeg)"
            selector = str(format_id) if has_audio else f"{format_id}+bestaudio[ext=m4a]/bestaudio/best"
            option = FormatOption(
                id=str(format_id),
                label=label,
                selector=selector,
                availability_id=str(format_id),
                ext="mp4",
                height=int(height),
                note=note,
                requires_ffmpeg=not has_audio,
            )

            previous = best_per_label.get(base_label)
            current_score = self._format_score(fmt)
            if previous is None:
                best_per_label[base_label] = option
                continue

            previous_score = 1 if "video+audio" in previous.note else 0
            if current_score > previous_score:
                best_per_label[base_label] = option

        return sorted(best_per_label.values(), key=lambda item: (item.height or 0, item.label), reverse=True)

    @staticmethod
    def _format_score(fmt: dict) -> int:
        return 1 if fmt.get("acodec") not in (None, "none") else 0

    def _build_progress_hook(
        self,
        task: DownloadTask,
        on_task_update: Optional[TaskCallback],
    ) -> Callable[[dict], None]:
        def hook(data: dict) -> None:
            if self._cancel_event.is_set():
                raise RuntimeError("Pobieranie zostało anulowane przez użytkownika.")

            status = data.get("status")
            if status == "downloading":
                downloaded = data.get("downloaded_bytes") or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                task.progress = round(downloaded / total * 100, 1) if total else task.progress
                task.filename = data.get("filename") or task.filename
                self._emit(on_task_update, task)
            elif status == "finished":
                task.progress = 100.0
                task.filename = data.get("filename") or task.filename
                self._emit(on_task_update, task)

        return hook

    @staticmethod
    def _emit(callback: Optional[TaskCallback], task: DownloadTask) -> None:
        if callback is not None:
            callback(copy.deepcopy(task))

    @staticmethod
    def _detect_ffmpeg_available() -> bool:
        if shutil.which("ffmpeg") is not None:
            return True

        winget_root = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        if not winget_root.exists():
            return False

        candidates = sorted(winget_root.rglob("ffmpeg.exe"), reverse=True)
        return any(candidate.is_file() for candidate in candidates)
