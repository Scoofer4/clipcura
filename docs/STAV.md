# Stav projektu Clipsana

Předávací zápis mezi relacemi. Aktualizovat na konci každé relace.

## 2. 11. 2026 – M1 (jádro, pravidla, profily, SQLite, CLI) – jádro hotové, čeká na commit

### Hotovo

- `clipsana/core`: `probe` (barvy čte ze snímků, ne z kontejneru; hloubkový test VFR z PTS; kontrolní
  dekódování přes ffprobe), `profiles` (YAML + pydantic, uživatelské profily v app data mají přednost),
  `planner` (všechny opravy v **jednom** ffmpeg příkazu, slučování filtrů, CPU záloha), `executor` (průběh,
  dočasný soubor a atomické přejmenování, úklid při chybě nebo zrušení, kontrola místa), `db` (SQLite WAL,
  audit log), `service` = veřejné API `scan/plan/apply/status/cancel`.
- 11 pravidel jako pluginy (jeden soubor = jedno pravidlo, hlášky EN/CS): vfr, fps_mismatch, hdr,
  hevc_10bit, resolution, audio_rate, rotation, no_audio, insv, corrupt a **color_space** (BT.601 → Rec.709,
  jen když se soubor převádí kvůli jinému problému). Kritérium „nové pravidlo jedním souborem“ je ověřené.
- CLI: `scan`, `plan`, `apply`, `fix` (`--dry-run`, `--deep`, `--force`, `--json`). Návratové kódy 0/1/2.
- Orientace se zachovává (na výšku zůstává na výšku), limit rozlišení platí pro delší stranu.
- Testy: 112 prošlo (jednotkové + integrační na klipech z lavfi + reálné vzorky přes `CLIPSANA_REAL_DIR`).
  CI si stahuje ffmpeg s cache.
- Reálné vzorky z `data/` převedené přes CUDA za 3 min 17 s: CFR 30/1, DNxHR HQ, PCM 48 kHz, rotace
  fyzicky provedená, opakovaný běh nic nepřevádí. Synchronizace zvuku odpovídá originálu.
- Opravené chyby nalezené na reálných vzorcích: falešné „poškozeno“ u záznamu obrazovky, emoji ve výpisu
  příkazu, zavádějící varování o trhání u VFR z telefonu, nekonzistentní barevné značky (BT.601 snímky
  v kontejneru označeném BT.709).

### Další krok

- Commit a push M1 (čeká na pokyn vlastníka).
- #5: měření cest (scale_cuda / libplacebo / CPU, dekódování) v doctoru a výběr nejrychlejší.
- #6: srozumitelná hláška pro videa menší než 256×120 (limit DNxHR).
- Pak M2 (lokální API, worker, WebSocket události).

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
- #6 DNxHR odmítá snímky menší než 256×120 – srozumitelná hláška v plánu (M1, low)
