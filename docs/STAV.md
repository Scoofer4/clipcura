# Stav projektu Clipsana

Předávací zápis mezi relacemi. Aktualizovat na konci každé relace.

## 2. 11. 2026 – M0 (prostředí + `clipsana doctor`)

### Hotovo

- Veřejný repozitář <https://github.com/Scoofer4/clipsana>, první commit `20e020d` (kostra ze zadání).
  Commity se podepisují noreply identitou Scoofer4, nastavenou lokálně v repozitáři.
- Python 3.12.15 přes uv (`.python-version`), `uv sync --group dev`.
- `tools/fetch_ffmpeg.py` stáhne zafixovaný build BtbN ffmpeg **8.1** (`autobuild-2026-11-02-12-51`),
  ověří SHA-256 a uloží ho do `vendor/ffmpeg` i s `BUILD.json` (zdroj a licence pro instalátor).
- `clipsana doctor` (`--json`, `--quick`, `--path`) zjistí OS, CPU, RAM, disky a GPU
  (nvidia-smi + Windows adaptéry bez virtuálních). Funkčně otestuje ffmpeg: zařízení CUDA/QSV/Vulkan,
  HW dekódování HEVC 10-bit, enkodéry NVENC/QSV/x264/DNxHR/ProRes a filtry libplacebo/zscale.
  Vybere backend CUDA → QSV → CPU a report uloží do `doctor.json` v app data
  (`%APPDATA%\Clipsana`, přepíše ho `CLIPSANA_HOME`).
- Testy: 21 prošlo, ruff čistý (lokálně).

### Rozpracováno / čeká na vlastníka

- M0 je v `main` (commit `960d2fe`, push se svolením vlastníka), CI zelené.
- Rozhodnutí vlastníka 2. 11. 2026 (zapsáno v CLAUDE.md):
  - referenční recept ze Shutter Encoderu nebude, aplikace má potřebné opravy zjistit sama (kap. 6);
  - vždy se použije kvalitnější nebo rychlejší cesta, mezi stejně kvalitními ta nejrychlejší podle měření
    na daném stroji, `scale_cuda` je povolený (kap. 4, issue #5).
- Vzorky ve složce `data/` (git je ignoruje): klip z telefonu (HEVC 8-bit 4K, VFR 60→58,3, rotace −90°)
  a dva záznamy obrazovky na výšku 1080×2340 se silným VFR (mezery mezi snímky až 0,9 s). Další vzorky dodá vlastník.
- Disk C: uklizen, vývojové cache a spouštěče jsou na D:.

### Issues

- #1 překlad komentářů v kostře do angličtiny (low)
- #2 `init_repo.ps1` (low)
- #3 CI selhává na ruffu – **uzavřeno** (opraveno v `960d2fe`, CI zelené)
- #4 ffmpeg 8.1 a `scale_cuda` – **uzavřeno** rozhodnutím
- #5 výběr nejrychlejší cesty stejné kvality podle měření (M1, medium)

### Další krok

Plán M1 (jádro, pravidla, profily, SQLite, CLI scan/plan/apply, issue #5).
Otevřená otázka do plánu M1: orientace na výšku (9:16) u záznamů obrazovky a telefonu vs. profil `social-30`.
