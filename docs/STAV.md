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

- M0 je commitnuté a pushnuté do `main` (se svolením vlastníka). Oprava CI (#3) je jeho součástí.
- Rozhodnutí o `scale_cuda` (#4).
- Úklid disku C: (pracovní data patří na D:), cílové adresáře potvrzuje vlastník.

### Issues

- #1 překlad komentářů v kostře do angličtiny (low)
- #2 `init_repo.ps1` (low)
- #3 CI selhává na ruffu (high, oprava v commitu M0)
- #4 ffmpeg 8.1 místo 7.x a otázka `scale_cuda` (medium, rozhodnutí)

### Další krok

Ověřit zelené CI, pak plán M1 (jádro, pravidla, profily, SQLite, CLI scan/plan/apply).
Pro M1 jsou potřeba podklady z kap. 15 zadání: nastavení Shutter Encoderu a vzorky videí.
