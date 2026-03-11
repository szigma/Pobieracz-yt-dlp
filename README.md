# Pobieracz wideo i audio

Desktopowa aplikacja w Pythonie do analizowania i pobierania wielu linków naraz z użyciem `yt-dlp`.

## Funkcje

- wklejanie wielu linków, po jednym w linii,
- analiza linków przed pobraniem,
- wybór folderu docelowego,
- tryb `MP4` albo `MP3`,
- domyślny wybór najlepszej jakości,
- ręczna zmiana jakości dla wybranego filmu,
- kolejka pobrań wykonywana po kolei,
- osobna obsługa błędów dla każdego linku,
- czytelna informacja, kiedy wybrana jakość wymaga `ffmpeg`.

## Wymagania

- Python 3.11+,
- `ffmpeg` w `PATH`, jeśli chcesz eksportować do `MP3` lub łączyć osobne strumienie obrazu i dźwięku w części filmów.

## Instalacja

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Uruchomienie

```powershell
cd D:\Pobieracz
python -m downloader_app
```

Albo bez wchodzenia do katalogu projektu:

```powershell
& "C:\Users\groco\AppData\Local\Programs\Python\Python312\python.exe" "D:\Pobieracz\run_app.py"
```

## Testy

```powershell
python -m unittest discover -s tests
```
