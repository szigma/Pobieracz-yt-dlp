from __future__ import annotations

import copy
import platform
import shutil
import subprocess
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
        self._platform = platform.system()
        self._ffmpeg_location = self._detect_ffmpeg_location()
        self._ffmpeg_available = self._ffmpeg_location is not None

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

    def is_ffmpeg_available(self) -> bool:
        return self._ffmpeg_available

    def refresh_ffmpeg_status(self) -> bool:
        self._ffmpeg_location = self._detect_ffmpeg_location()
        self._ffmpeg_available = self._ffmpeg_location is not None
        return self._ffmpeg_available

    def install_ffmpeg(self) -> tuple[bool, str]:
        if platform.system() != "Windows":
            return False, "Automatyczna instalacja ffmpeg jest obslugiwana tylko na Windows."

        winget = shutil.which("winget")
        if winget is None:
            return False, "Nie znaleziono winget. Zainstaluj ffmpeg recznie: winget install Gyan.FFmpeg.Essentials"

        result = subprocess.run(
            [
                winget,
                "install",
                "-e",
                "--id",
                "Gyan.FFmpeg.Essentials",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        installed = self.refresh_ffmpeg_status()
        if result.returncode == 0 and installed:
            return True, "ffmpeg zostal zainstalowany i jest gotowy do uzycia."

        details = (result.stderr or "").strip() or (result.stdout or "").strip()
        if not details:
            details = "Instalacja ffmpeg nie powiodla sie."
        return False, details

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
                self.refresh_ffmpeg_status()
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

                selector = self._resolve_download_selector(task, info)
                final_path = self._download_task(task, output_path, info, selector, on_task_update)
                if task.mode == DownloadMode.VIDEO and self._is_linux():
                    self._ensure_linux_video_has_audio(task, output_path, info, final_path, on_task_update)
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
        info: dict,
        selector: str,
        on_task_update: Optional[TaskCallback],
    ) -> Path:
        final_path = self._build_output_path(task, output_path, info)
        outtmpl = str(final_path)
        options = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._build_progress_hook(task, on_task_update)],
            "overwrites": False,
        }
        if self._ffmpeg_location is not None:
            options["ffmpeg_location"] = self._ffmpeg_location

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
            options["format"] = selector
            if self._ffmpeg_available:
                options["merge_output_format"] = "mp4"

        with YoutubeDL(options) as ydl:
            ydl.download([task.url])
        return final_path

    def _resolve_format_selector(self, task: DownloadTask) -> str:
        if task.selected_format == "auto":
            if self._is_x_url(task.url):
                return (
                    "best[ext=mp4][vcodec!=none][acodec!=none]/"
                    "best[vcodec!=none][acodec!=none]/"
                    "best[ext=mp4][vcodec!=none]/"
                    "best[vcodec!=none]"
                )
            if not self._ffmpeg_available:
                return "best[ext=mp4][acodec!=none]/best[acodec!=none]"
            if self._is_linux():
                return (
                    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo+bestaudio/"
                    "best[ext=mp4][acodec!=none]/"
                    "best[acodec!=none]"
                )
            return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"

        selected = next((item for item in task.available_formats if item.id == task.selected_format), None)
        if selected is None:
            raise RuntimeError("Wybrana jakość nie jest już dostępna w pamięci aplikacji.")
        return self._build_selected_format_selector(task, selected)

    def _ensure_selected_format_available(self, task: DownloadTask, info: dict) -> None:
        current_ids = {str(fmt.get("format_id")) for fmt in info.get("formats", []) if fmt.get("format_id")}
        selected = next((item for item in task.available_formats if item.id == task.selected_format), None)
        if selected is None or selected.availability_id not in current_ids:
            raise RuntimeError("Wybrana jakość nie jest już dostępna dla tego filmu.")

    def _resolve_download_selector(self, task: DownloadTask, info: dict) -> str:
        if task.mode != DownloadMode.VIDEO:
            return "bestaudio/best"

        if task.selected_format != "auto":
            return self._resolve_format_selector(task)

        if self._is_x_url(task.url):
            current_formats = self._build_video_formats(info)
            if current_formats:
                return "/".join(option.id for option in current_formats)

        return self._resolve_format_selector(task)

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

    def _build_output_path(self, task: DownloadTask, output_path: Path, info: dict) -> Path:
        info_for_name = dict(info)
        if task.mode == DownloadMode.AUDIO:
            info_for_name["ext"] = "mp3"
        elif self._ffmpeg_available:
            info_for_name["ext"] = "mp4"
        else:
            info_for_name["ext"] = info.get("ext") or "mp4"

        template = str(output_path / "%(title)s [%(id)s].%(ext)s")
        with YoutubeDL({"quiet": True, "outtmpl": template}) as ydl:
            base_path = Path(ydl.prepare_filename(info_for_name))
        return self._next_available_path(base_path)

    def _build_video_formats(self, info: dict) -> list[FormatOption]:
        formats = info.get("formats") or []
        best_per_label: dict[str, FormatOption] = {}

        for fmt in formats:
            format_id = fmt.get("format_id")
            ext = (fmt.get("ext") or "").lower()
            if not format_id:
                continue
            if ext and ext != "mp4":
                continue

            has_video = self._format_has_video(fmt)
            if not has_video:
                continue

            height = fmt.get("height")
            if not height:
                continue

            has_audio = self._format_has_audio(fmt)
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
        return 1 if DownloaderService._format_has_audio(fmt) else 0

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
    def _detect_ffmpeg_location() -> str | None:
        detected = shutil.which("ffmpeg")
        if detected is not None:
            return str(Path(detected).parent)

        winget_root = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
        if not winget_root.exists():
            return None

        candidates = sorted(winget_root.rglob("ffmpeg.exe"), reverse=True)
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.parent)
        return None

    @staticmethod
    def _is_x_url(url: str) -> bool:
        lowered = url.lower()
        return "x.com/" in lowered or "twitter.com/" in lowered

    @staticmethod
    def _format_has_video(fmt: dict) -> bool:
        vcodec = fmt.get("vcodec")
        protocol = (fmt.get("protocol") or "").lower()
        return vcodec not in (None, "none") or protocol in {"http", "https"}

    @staticmethod
    def _format_has_audio(fmt: dict) -> bool:
        acodec = fmt.get("acodec")
        protocol = (fmt.get("protocol") or "").lower()
        return acodec not in (None, "none") or protocol in {"http", "https"}

    @staticmethod
    def _next_available_path(path: Path) -> Path:
        if not path.exists():
            return path

        stem = path.stem
        suffix = path.suffix
        parent = path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _build_selected_format_selector(self, task: DownloadTask, selected: FormatOption) -> str:
        if not selected.requires_ffmpeg:
            return selected.selector

        if selected.height is None:
            selector = (
                f"{selected.availability_id}+bestaudio[ext=m4a]/"
                f"{selected.availability_id}+bestaudio/"
                "best[ext=mp4][acodec!=none]/best[acodec!=none]"
            )
            if not self._is_linux():
                selector = f"{selector}/best"
            return selector

        same_or_lower_progressive = [
            option.selector
            for option in task.available_formats
            if not option.requires_ffmpeg
            and option.height is not None
            and option.height <= selected.height
        ]
        fallback_parts = [
            f"bestvideo[height<={selected.height}][ext=mp4]+bestaudio[ext=m4a]",
            f"bestvideo[height<={selected.height}]+bestaudio",
            f"{selected.availability_id}+bestaudio[ext=m4a]",
            f"{selected.availability_id}+bestaudio",
            *same_or_lower_progressive,
            f"best[height<={selected.height}][ext=mp4][acodec!=none]",
            f"best[height<={selected.height}][acodec!=none]",
            "best[ext=mp4][acodec!=none]",
            "best[acodec!=none]",
        ]
        if not self._is_linux():
            fallback_parts.append("best")
        return "/".join(dict.fromkeys(fallback_parts))

    def _ensure_linux_video_has_audio(
        self,
        task: DownloadTask,
        output_path: Path,
        info: dict,
        final_path: Path,
        on_task_update: Optional[TaskCallback],
    ) -> None:
        if not final_path.exists() or self._file_has_audio_track(final_path):
            return

        retry_selector = self._build_linux_audio_safe_retry_selector(task)
        if not retry_selector:
            raise RuntimeError(
                "Linux pobral plik bez dzwieku i nie znaleziono bezpiecznego formatu awaryjnego z audio."
            )

        final_path.unlink(missing_ok=True)
        task.status = "Retrying audio-safe format"
        task.progress = 0.0
        task.error_message = ""
        self._emit(on_task_update, task)
        retried_path = self._download_task(task, output_path, info, retry_selector, on_task_update)
        if not retried_path.exists() or not self._file_has_audio_track(retried_path):
            raise RuntimeError(
                "Linux nie mogl zapisac pliku z dzwiekiem. Sprawdz ffmpeg i sprobuj nizszej jakosci albo Auto."
            )

    def _build_linux_audio_safe_retry_selector(self, task: DownloadTask) -> str:
        if task.selected_format == "auto":
            return "best[ext=mp4][acodec!=none]/best[acodec!=none]"

        selected = next((item for item in task.available_formats if item.id == task.selected_format), None)
        if selected is None or selected.height is None:
            return "best[ext=mp4][acodec!=none]/best[acodec!=none]"

        same_or_lower_progressive = [
            option.selector
            for option in task.available_formats
            if not option.requires_ffmpeg
            and option.height is not None
            and option.height <= selected.height
        ]
        retry_parts = [
            *same_or_lower_progressive,
            f"best[height<={selected.height}][ext=mp4][acodec!=none]",
            f"best[height<={selected.height}][acodec!=none]",
            "best[ext=mp4][acodec!=none]",
            "best[acodec!=none]",
        ]
        return "/".join(dict.fromkeys(retry_parts))

    def _file_has_audio_track(self, path: Path) -> bool:
        ffprobe_command = self._resolve_ffprobe_command()
        if ffprobe_command is None:
            return True

        result = subprocess.run(
            [
                ffprobe_command,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and bool(result.stdout.strip())

    def _resolve_ffprobe_command(self) -> str | None:
        ffprobe = shutil.which("ffprobe")
        if ffprobe is not None:
            return ffprobe

        if self._ffmpeg_location is None:
            return None

        binary_name = "ffprobe.exe" if platform.system() == "Windows" else "ffprobe"
        candidate = Path(self._ffmpeg_location) / binary_name
        if candidate.exists():
            return str(candidate)
        return None

    def _is_linux(self) -> bool:
        return self._platform == "Linux"
