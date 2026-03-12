import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from downloader_app.downloader import DownloaderService, parse_urls
from downloader_app.models import DownloadMode, DownloadTask


class ParseUrlsTests(unittest.TestCase):
    def test_parse_urls_removes_empty_lines_and_duplicates(self) -> None:
        raw = """
        https://example.com/a

        https://example.com/a
        https://example.com/b
        """
        self.assertEqual(
            parse_urls(raw),
            ["https://example.com/a", "https://example.com/b"],
        )


class FormatSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DownloaderService()

    def test_build_video_formats_deduplicates_resolutions(self) -> None:
        info = {
            "formats": [
                {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "mp4a"},
                {"format_id": "134", "ext": "mp4", "height": 360, "vcodec": "avc1", "acodec": "none"},
                {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a"},
                {"format_id": "248", "ext": "webm", "height": 1080, "vcodec": "vp9", "acodec": "none"},
            ]
        }

        options = self.service._build_video_formats(info)

        self.assertEqual([item.label for item in options], ["720p mp4", "360p mp4"])
        self.assertEqual(options[1].id, "18")

    def test_build_video_formats_marks_ffmpeg_requirement(self) -> None:
        info = {
            "formats": [
                {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none"}
            ]
        }

        options = self.service._build_video_formats(info)

        self.assertEqual(options[0].label, "1080p mp4 (wymaga ffmpeg)")
        self.assertTrue(options[0].requires_ffmpeg)

    def test_build_video_formats_accepts_x_progressive_http_mp4(self) -> None:
        info = {
            "formats": [
                {
                    "format_id": "http-950",
                    "ext": "mp4",
                    "protocol": "https",
                    "height": 964,
                    "width": 480,
                    "vcodec": None,
                    "acodec": None,
                }
            ]
        }

        options = self.service._build_video_formats(info)

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].label, "964p mp4")
        self.assertFalse(options[0].requires_ffmpeg)

    def test_build_video_formats_does_not_treat_generic_https_video_only_as_audio(self) -> None:
        info = {
            "formats": [
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "protocol": "https",
                    "height": 1080,
                    "vcodec": "avc1",
                    "acodec": "none",
                }
            ]
        }

        options = self.service._build_video_formats(info)

        self.assertEqual(options[0].label, "1080p mp4 (wymaga ffmpeg)")
        self.assertTrue(options[0].requires_ffmpeg)

    def test_set_selected_format_updates_label(self) -> None:
        task = DownloadTask(id="task-1", url="https://example.com", mode=DownloadMode.VIDEO)
        task.available_formats = self.service._build_video_formats(
            {
                "formats": [
                    {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a"}
                ]
            }
        )
        self.service._tasks[task.id] = task
        updated = self.service.set_selected_format(task.id, "22")
        self.assertEqual(updated.selected_format, "22")
        self.assertEqual(updated.selected_format_label, "720p mp4")

    def test_auto_selector_prefers_complete_mp4_for_x(self) -> None:
        task = DownloadTask(id="task-x", url="https://x.com/user/status/123", mode=DownloadMode.VIDEO)
        self.service._tasks[task.id] = task

        selector = self.service._resolve_format_selector(task)

        self.assertIn("best[ext=mp4][vcodec!=none][acodec!=none]", selector)
        self.assertNotIn("bestvideo[ext=mp4]+bestaudio[ext=m4a]", selector)

    def test_download_selector_uses_real_x_format_ids_for_auto(self) -> None:
        task = DownloadTask(id="task-x2", url="https://x.com/user/status/123", mode=DownloadMode.VIDEO)
        info = {
            "formats": [
                {"format_id": "http-950", "ext": "mp4", "protocol": "https", "height": 964},
                {"format_id": "http-632", "ext": "mp4", "protocol": "https", "height": 642},
            ]
        }

        selector = self.service._resolve_download_selector(task, info)

        self.assertEqual(selector, "http-950/http-632")

    def test_selected_format_selector_prefers_audio_safe_fallbacks(self) -> None:
        task = DownloadTask(id="task-2", url="https://example.com", mode=DownloadMode.VIDEO)
        task.available_formats = self.service._build_video_formats(
            {
                "formats": [
                    {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none"},
                    {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a"},
                ]
            }
        )
        self.service._tasks[task.id] = task
        selected = next(option for option in task.available_formats if option.id == "137")

        selector = self.service._build_selected_format_selector(task, selected)

        self.assertIn("bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]", selector)
        self.assertIn("137+bestaudio[ext=m4a]", selector)
        self.assertIn("22", selector)
        self.assertNotEqual(selector, "137")

    def test_linux_manual_selector_does_not_fallback_to_video_only(self) -> None:
        linux_service = DownloaderService()
        linux_service._platform = "Linux"
        task = DownloadTask(id="task-3", url="https://example.com", mode=DownloadMode.VIDEO)
        task.available_formats = linux_service._build_video_formats(
            {
                "formats": [
                    {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none"},
                    {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a"},
                ]
            }
        )
        selected = next(option for option in task.available_formats if option.id == "137")

        selector = linux_service._build_selected_format_selector(task, selected)

        self.assertFalse(selector.endswith("/best"))
        self.assertIn("best[acodec!=none]", selector)

    def test_linux_auto_selector_requires_audio(self) -> None:
        linux_service = DownloaderService()
        linux_service._platform = "Linux"
        linux_service._ffmpeg_available = False

        task = DownloadTask(id="task-4", url="https://example.com", mode=DownloadMode.VIDEO)
        selector = linux_service._resolve_format_selector(task)

        self.assertEqual(selector, "best[ext=mp4][acodec!=none]/best[acodec!=none]")

    def test_linux_audio_safe_retry_selector_prefers_progressive_with_audio(self) -> None:
        linux_service = DownloaderService()
        linux_service._platform = "Linux"
        task = DownloadTask(id="task-5", url="https://example.com", mode=DownloadMode.VIDEO)
        task.available_formats = linux_service._build_video_formats(
            {
                "formats": [
                    {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none"},
                    {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a"},
                ]
            }
        )
        task.selected_format = "137"

        selector = linux_service._build_linux_audio_safe_retry_selector(task)

        self.assertTrue(selector.startswith("22"))
        self.assertNotIn("/bestvideo", selector)


class LinuxAudioGuardTests(unittest.TestCase):
    def test_linux_retries_when_first_file_has_no_audio(self) -> None:
        service = DownloaderService()
        service._platform = "Linux"
        task = DownloadTask(id="task-linux", url="https://example.com/video", mode=DownloadMode.VIDEO)
        output_dir = Path("D:/Pobieracz")
        info = {"title": "Film", "id": "abc123", "ext": "mp4"}
        final_path = output_dir / "Film [abc123].mp4"

        with patch.object(service, "_file_has_audio_track", side_effect=[False, True]):
            with patch.object(service, "_build_linux_audio_safe_retry_selector", return_value="safe-selector"):
                with patch.object(service, "_download_task", side_effect=[final_path, final_path]) as download_mock:
                    with patch.object(Path, "exists", return_value=True):
                        with patch.object(Path, "unlink") as unlink_mock:
                            service._ensure_linux_video_has_audio(task, output_dir, info, final_path, None)

        self.assertEqual(download_mock.call_count, 1)
        self.assertEqual(download_mock.call_args.args[3], "safe-selector")
        unlink_mock.assert_called_once()


class FileCollisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DownloaderService()

    def test_next_available_path_returns_same_path_when_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "Film [abc123].mp4"
            self.assertEqual(self.service._next_available_path(path), path)

    def test_next_available_path_adds_incrementing_suffix_for_mp4(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "Film [abc123].mp4"
            base.touch()
            first = self.service._next_available_path(base)
            self.assertEqual(first.name, "Film [abc123] (1).mp4")
            first.touch()
            second = self.service._next_available_path(base)
            self.assertEqual(second.name, "Film [abc123] (2).mp4")

    def test_next_available_path_adds_incrementing_suffix_for_mp3(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "Film [abc123].mp3"
            base.touch()
            self.assertEqual(self.service._next_available_path(base).name, "Film [abc123] (1).mp3")

    def test_download_task_uses_non_overwriting_outtmpl_settings(self) -> None:
        service = DownloaderService()
        task = DownloadTask(id="task-1", url="https://example.com/video", mode=DownloadMode.VIDEO)
        info = {"title": "Film", "id": "abc123", "ext": "mp4"}

        with patch("downloader_app.downloader.YoutubeDL") as ydl_mock:
            ydl_instance = ydl_mock.return_value.__enter__.return_value
            ydl_instance.prepare_filename.return_value = "D:/Pobieracz/Film [abc123].mp4"
            service._download_task(task, Path("D:/Pobieracz"), info, "best", None)

        options = ydl_mock.call_args_list[-1].args[0]
        self.assertFalse(options["overwrites"])
        self.assertEqual(options["outtmpl"], "D:\\Pobieracz\\Film [abc123].mp4")

    def test_build_output_path_adds_suffix_when_file_exists(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "Film [abc123].mp4"
            base.touch()
            task = DownloadTask(id="task-1", url="https://example.com/video", mode=DownloadMode.VIDEO)
            info = {"title": "Film", "id": "abc123", "ext": "mp4"}

            path = self.service._build_output_path(task, Path(tmpdir), info)

            self.assertEqual(path.name, "Film [abc123] (1).mp4")

    def test_build_output_path_uses_mp3_extension_for_audio(self) -> None:
        with TemporaryDirectory() as tmpdir:
            task = DownloadTask(id="task-1", url="https://example.com/audio", mode=DownloadMode.AUDIO)
            info = {"title": "Film", "id": "abc123", "ext": "webm"}

            path = self.service._build_output_path(task, Path(tmpdir), info)

            self.assertEqual(path.name, "Film [abc123].mp3")


class FfmpegTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DownloaderService()

    def test_refresh_ffmpeg_status_returns_false_when_detector_fails(self) -> None:
        with patch.object(self.service, "_detect_ffmpeg_location", return_value=None):
            self.assertFalse(self.service.refresh_ffmpeg_status())
            self.assertFalse(self.service.is_ffmpeg_available())

    def test_install_ffmpeg_returns_manual_message_when_winget_missing(self) -> None:
        with patch("downloader_app.downloader.platform.system", return_value="Windows"):
            with patch("downloader_app.downloader.shutil.which", return_value=None):
                success, message = self.service.install_ffmpeg()

        self.assertFalse(success)
        self.assertIn("winget install Gyan.FFmpeg.Essentials", message)

    def test_install_ffmpeg_reports_success_when_command_and_refresh_succeed(self) -> None:
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch("downloader_app.downloader.platform.system", return_value="Windows"):
            with patch("downloader_app.downloader.shutil.which", return_value="C:/Windows/System32/winget.exe"):
                with patch("downloader_app.downloader.subprocess.run", return_value=completed):
                    with patch.object(self.service, "refresh_ffmpeg_status", return_value=True):
                        self.service._ffmpeg_available = True
                        success, message = self.service.install_ffmpeg()

        self.assertTrue(success)
        self.assertIn("ffmpeg zostal zainstalowany", message)


if __name__ == "__main__":
    unittest.main()
