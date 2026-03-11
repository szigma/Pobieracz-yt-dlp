import unittest

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


if __name__ == "__main__":
    unittest.main()
