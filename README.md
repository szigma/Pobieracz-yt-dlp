# Pobieracz wideo i audio

Desktopowa aplikacja w Pythonie do analizowania i pobierania wielu linkow naraz z uzyciem `yt-dlp`.

## Funkcje

- wklejanie wielu linkow, po jednym w linii,
- analiza linkow przed pobraniem,
- wybor folderu docelowego,
- tryb `MP4` albo `MP3`,
- domyslny wybor najlepszej jakosci,
- reczna zmiana jakosci dla wybranego filmu,
- kolejkowanie pobran wykonywanych po kolei,
- automatyczne numerowanie plikow przy konflikcie nazw,
- osobna obsluga bledow dla kazdego linku,
- informacja, kiedy wybrana jakosc wymaga `ffmpeg`,
- wskaznik statusu `ffmpeg` w aplikacji,
- przycisk automatycznej instalacji `ffmpeg` na Windows.

## Wymagania

- Python 3.11 lub nowszy,
- `ffmpeg` w `PATH`, jesli chcesz eksportowac do `MP3` albo laczyc osobne strumienie obrazu i dzwieku.

## Instalacja

1. Sklonuj repozytorium albo pobierz kod z GitHuba.
2. Przejdz do katalogu projektu.
3. Utworz i aktywuj wirtualne srodowisko.
4. Zainstaluj zaleznosci.

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uruchomienie z kodu

### Windows PowerShell

```powershell
python -m downloader_app
```

### macOS / Linux

```bash
python3 -m downloader_app
```

## Uruchomienie gotowej aplikacji na Windows

Jesli korzystasz z gotowego wydania, pobierz `Pobieracz-yt-dlp.exe` z sekcji Releases i uruchom plik bez instalowania Pythona.

## ffmpeg w aplikacji

Aplikacja sprawdza przy starcie, czy `ffmpeg` jest dostepny.

- jesli `ffmpeg` jest zainstalowany, zobaczysz status `ffmpeg: zainstalowany`,
- jesli go brakuje, zobaczysz status `ffmpeg: brak`,
- na Windows pojawi sie przycisk `Zainstaluj ffmpeg`, ktory probuje wykonac instalacje przez `winget`.

Po udanej instalacji status w aplikacji odswieza sie bez restartu programu.

## Instalacja ffmpeg

`ffmpeg` jest potrzebny do:

- eksportu do `MP3`,
- laczenia osobnych strumieni obrazu i dzwieku przy czesci filmow.

### Windows

Najprosciej przez `winget`:

```powershell
winget install Gyan.FFmpeg.Essentials
```

Po instalacji uruchom ponownie terminal i sprawdz:

```powershell
ffmpeg -version
```

### macOS

Przez Homebrew:

```bash
brew install ffmpeg
```

Sprawdzenie:

```bash
ffmpeg -version
```

### Linux

Ubuntu / Debian:

```bash
sudo apt update
sudo apt install ffmpeg
```

Fedora:

```bash
sudo dnf install ffmpeg
```

Arch Linux:

```bash
sudo pacman -S ffmpeg
```

Sprawdzenie:

```bash
ffmpeg -version
```

## Testy

### Windows PowerShell

```powershell
python -m unittest discover -s tests
```

### macOS / Linux

```bash
python3 -m unittest discover -s tests
```

## Uwagi

- Niektore serwisy moga wymagac `ffmpeg`, nawet przy pobieraniu wideo.
- Jesli plik o tej samej nazwie juz istnieje, aplikacja zapisze nowy plik z dopiskiem ` (1)`, ` (2)` itd.
