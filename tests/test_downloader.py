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


if __name__ == "__main__":
    unittest.main()
