from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from .downloader import DownloaderService, parse_urls
from .models import DownloadMode, DownloadTask


class DownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Pobieracz multimediów")
        self.root.geometry("1180x720")
        self.root.minsize(980, 620)

        self.service = DownloaderService()
        self.tasks: dict[str, DownloadTask] = {}
        self.message_queue: queue.Queue[DownloadTask] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None

        self.mode_var = tk.StringVar(value=DownloadMode.VIDEO.value)
        self.output_dir_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self.status_var = tk.StringVar(value="Wklej linki i kliknij Analizuj.")
        self.selected_task_id: Optional[str] = None
        self.format_lookup: dict[str, str] = {}

        self._build_ui()
        self.root.after(150, self._process_queue)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.root, padding=12)
        controls.grid(row=0, column=0, sticky="nsew")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)

        urls_frame = ttk.LabelFrame(controls, text="Linki", padding=10)
        urls_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        urls_frame.columnconfigure(0, weight=1)
        urls_frame.rowconfigure(0, weight=1)

        self.urls_text = tk.Text(urls_frame, height=10, wrap="word")
        self.urls_text.grid(row=0, column=0, sticky="nsew")

        options_frame = ttk.LabelFrame(controls, text="Ustawienia", padding=10)
        options_frame.grid(row=0, column=1, sticky="nsew")
        options_frame.columnconfigure(1, weight=1)

        ttk.Label(options_frame, text="Tryb:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            options_frame,
            text="Wideo MP4",
            value=DownloadMode.VIDEO.value,
            variable=self.mode_var,
            command=self._on_mode_changed,
        ).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            options_frame,
            text="Audio MP3",
            value=DownloadMode.AUDIO.value,
            variable=self.mode_var,
            command=self._on_mode_changed,
        ).grid(row=0, column=2, sticky="w")

        ttk.Label(options_frame, text="Folder zapisu:").grid(row=1, column=0, sticky="w", pady=(12, 0))
        folder_entry = ttk.Entry(options_frame, textvariable=self.output_dir_var)
        folder_entry.grid(row=1, column=1, sticky="ew", pady=(12, 0), padx=(0, 8))
        ttk.Button(options_frame, text="Wybierz", command=self._choose_output_dir).grid(
            row=1, column=2, sticky="ew", pady=(12, 0)
        )

        buttons = ttk.Frame(options_frame)
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        buttons.columnconfigure((0, 1, 2), weight=1)

        self.analyze_button = ttk.Button(buttons, text="Analizuj linki", command=self._analyze_urls)
        self.analyze_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.start_button = ttk.Button(buttons, text="Pobierz", command=self._start_downloads)
        self.start_button.grid(row=0, column=1, sticky="ew", padx=6)
        self.cancel_button = ttk.Button(buttons, text="Anuluj", command=self._cancel_downloads, state="disabled")
        self.cancel_button.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        table_frame = ttk.LabelFrame(self.root, text="Kolejka", padding=12)
        table_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("title", "url", "status", "quality", "progress", "error")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        headings = {
            "title": "Tytuł",
            "url": "URL",
            "status": "Status",
            "quality": "Jakość",
            "progress": "Postęp",
            "error": "Błąd",
        }
        widths = {"title": 250, "url": 250, "status": 100, "quality": 120, "progress": 90, "error": 250}
        for name in columns:
            self.tree.heading(name, text=headings[name])
            self.tree.column(name, width=widths[name], anchor="w", stretch=True)

        tree_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_selected)

        format_frame = ttk.LabelFrame(self.root, text="Wybrana jakość", padding=12)
        format_frame.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        format_frame.columnconfigure(1, weight=1)

        ttk.Label(format_frame, text="Format dla zaznaczonego filmu:").grid(row=0, column=0, sticky="w")
        self.format_var = tk.StringVar(value="auto")
        self.format_combo = ttk.Combobox(format_frame, textvariable=self.format_var, state="disabled")
        self.format_combo.grid(row=0, column=1, sticky="ew", padx=8)
        self.format_combo.bind("<<ComboboxSelected>>", self._on_quality_changed)

        ttk.Label(self.root, textvariable=self.status_var, padding=(12, 0, 12, 12)).grid(
            row=3, column=0, sticky="ew"
        )

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(Path.home()))
        if selected:
            self.output_dir_var.set(selected)

    def _analyze_urls(self) -> None:
        urls = parse_urls(self.urls_text.get("1.0", "end"))
        if not urls:
            messagebox.showwarning("Brak linków", "Wklej co najmniej jeden link.")
            return

        self.tasks.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._set_busy(True, "Analizowanie linków...")

        mode = DownloadMode(self.mode_var.get())
        self.worker_thread = threading.Thread(target=self._run_analysis, args=(urls, mode), daemon=True)
        self.worker_thread.start()

    def _run_analysis(self, urls: list[str], mode: DownloadMode) -> None:
        try:
            tasks = self.service.analyze_urls(urls, mode, on_task_update=self.message_queue.put)
            for task in tasks:
                self.message_queue.put(task)
        finally:
            self.message_queue.put(
                DownloadTask(
                    id="__system__",
                    url="",
                    mode=mode,
                    status="__analysis_done__",
                    title=f"Analiza zakończona. Znaleziono {len(tasks)} pozycji.",
                )
            )

    def _start_downloads(self) -> None:
        if not self.tasks:
            messagebox.showwarning("Brak zadań", "Najpierw przeanalizuj linki.")
            return

        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("Brak folderu", "Wybierz folder docelowy.")
            return

        ready_tasks = [task for task in self.tasks.values() if task.status != "Error"]
        if not ready_tasks:
            messagebox.showwarning("Brak poprawnych zadań", "Nie ma żadnych poprawnych linków do pobrania.")
            return

        self._set_busy(True, "Pobieranie w toku...")
        self.worker_thread = threading.Thread(
            target=self._run_downloads,
            args=(ready_tasks, output_dir),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_downloads(self, tasks: list[DownloadTask], output_dir: str) -> None:
        mode = DownloadMode(self.mode_var.get())
        try:
            self.service.start_queue(tasks, output_dir, on_task_update=self.message_queue.put)
        finally:
            self.message_queue.put(
                DownloadTask(
                    id="__system__",
                    url="",
                    mode=mode,
                    status="__downloads_done__",
                    title="Pobieranie zakończone.",
                )
            )

    def _cancel_downloads(self) -> None:
        self.service.cancel_current()
        self.status_var.set("Anulowanie bieżącego pobierania...")

    def _on_mode_changed(self) -> None:
        if self.tasks:
            self.status_var.set("Po zmianie trybu ponownie przeanalizuj linki.")

    def _process_queue(self) -> None:
        try:
            while True:
                task = self.message_queue.get_nowait()
                if task.id == "__system__":
                    if task.status == "__analysis_done__":
                        self._set_busy(False, task.title or "Analiza zakończona.")
                    elif task.status == "__downloads_done__":
                        self._set_busy(False, task.title or "Pobieranie zakończone.")
                    continue
                self._upsert_task(task)
        except queue.Empty:
            pass
        self.root.after(150, self._process_queue)

    def _upsert_task(self, task: DownloadTask) -> None:
        self.tasks[task.id] = task
        values = (
            task.title or task.url,
            task.url,
            task.status,
            task.selected_format_label,
            f"{task.progress:.1f}%",
            task.error_message,
        )
        if self.tree.exists(task.id):
            self.tree.item(task.id, values=values)
        else:
            self.tree.insert("", "end", iid=task.id, values=values)

        if self.selected_task_id == task.id:
            self._refresh_quality_controls(task)

    def _on_tree_selected(self, _event: object) -> None:
        selected = self.tree.selection()
        if not selected:
            self.selected_task_id = None
            self.format_lookup = {}
            self.format_combo.configure(state="disabled", values=[])
            self.format_var.set("")
            return

        task_id = selected[0]
        self.selected_task_id = task_id
        self._refresh_quality_controls(self.tasks[task_id])

    def _refresh_quality_controls(self, task: DownloadTask) -> None:
        if task.mode != DownloadMode.VIDEO or task.status == "Error":
            self.format_lookup = {}
            self.format_combo.configure(state="disabled", values=[])
            self.format_var.set("MP3" if task.mode == DownloadMode.AUDIO else "")
            return

        display_pairs = [("Auto", "auto")] + [(option.label, option.id) for option in task.available_formats]
        self.format_lookup = {label: format_id for label, format_id in display_pairs}
        self.format_combo.configure(state="readonly", values=[label for label, _ in display_pairs])
        display_value = "Auto" if task.selected_format == "auto" else task.selected_format_label
        self.format_var.set(display_value)

    def _on_quality_changed(self, _event: object) -> None:
        if not self.selected_task_id:
            return

        task = self.tasks[self.selected_task_id]
        if task.mode != DownloadMode.VIDEO:
            return

        selected_label = self.format_var.get()
        selected_id = self.format_lookup.get(selected_label)
        if selected_id is None:
            messagebox.showerror("Błąd formatu", "Nie udało się dopasować wybranej jakości.")
            return

        updated = self.service.set_selected_format(task.id, selected_id)
        self._upsert_task(updated)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_var.set(status)
        self.analyze_button.configure(state="disabled" if busy else "normal")
        self.start_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")


def run() -> None:
    root = tk.Tk()
    app = DownloaderApp(root)
    root.mainloop()
