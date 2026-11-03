# Stav projektu Clipcura

Předávací zápis mezi relacemi. Aktualizovat na konci každé relace.

## 3. 11. 2026 (odpoledne) – přenosný ZIP, režim prohlížeče, aktualizace se souhlasem, log

### Hotovo

- **#21 balíčky:** každé vydání má instalátor i přenosný ZIP (+ `SHA256SUMS.txt`). Přenosná kopie má
  `portable.txt` a data drží ve složce `data` vedle sebe (na médiu jen pro čtení spadne do `%APPDATA%`).
  Workflow `release.yml`: tag verze → sestavení na GitHub Actions → **koncept** vydání (zveřejňuje vlastník).
  O aplikaci a `clipcura version` ukazují druh kopie a složku dat.
- **#23 režim prohlížeče:** `Clipcura.exe --browser`, volba v Nastavení, automaticky bez WebView2. Prohlížeč
  dostane jednorázový kód (2 min, jednou), nikdy klíč. Instalátor bez WebView2 už neblokuje.
  macOS/Linux se neřeší (rozhodnutí vlastníka), nápad na iPad v #24.
- **#22 aktualizace a chybějící části:** při prvním spuštění se aplikace zeptá na denní kontrolu GitHubu;
  stažení jen tlačítkem, ověření SHA-256, instalátor / rozbalení vedle a přepnutí i s daty. Obnova FFmpeg
  (jen zafixovaný build) a instalace WebView2 (podpis Microsoftu ověřen). Nastavení → Aktualizace,
  `clipcura update`. AI jen čte.
- **#25:** zafixovaný denní build FFmpeg by BtbN za 14 dní smazal → pin na měsíční build 2026-10-31 (8.1.3)
  a pevný SHA-256. Kalibrace GPU na notebooku vyšla stejně.
- **#26 log:** každý proces (aplikace, služba, MCP, CLI) loguje od spuštění do ukončení do `<data>/logs/`
  (JSON řádky, rotace 5 × 5 MB), neošetřené chyby, `crash.log` pro pády mimo Python. Klíč a kódy maskované.
  Obrazovka **Log** (živě, filtr, hledání, kopírování), MCP `get_logs`, `clipcura logs`.
  **Log se nikdy nemaže** (ani po pádu, ani po řádném konci); další start zapíše, že předchozí běh neskončil
  normálně.
- Opraveno při ověřování: spouštěná kopie GUI bez konzole se zasekla, když zdědila standardní proudy
  (restart do nové verze) → spouští se se zahozenými proudy.

### Ověřeno

- pytest 275 prošlo / 2 přeskočeny, ruff, tsc, Playwright 14/14 v Edge a e2e v Chrome, CI zelené.
- Workflow vydání (ruční běh) sestavil ZIP + instalátor + součty na Actions.
- Zabalená přenosná kopie (cesta s mezerou): data vedle sebe, API hlásí `portable`, ukončení z ikony,
  restart (`/api/restart`) → nový proces, tvrdé zabití → log zůstal a další start nahlásil pád.
- **Neověřeno:** Firefox (Playwright ho bez vlastního buildu neovládá; headless snímek nic neprokázal),
  skutečné stažení nové verze z GitHubu (žádné vydání zatím neexistuje; ověřeno s falešným zdrojem),
  instalace WebView2 na stroji bez něj, instalace na čistých Windows.

### Otevřené

- **Vydání v0.1.0 je připravené jako koncept** (tag `v0.1.0` na 1dea09c, se souhlasem vlastníka):
  ZIP + instalátor + `SHA256SUMS.txt`, součty ověřené po stažení, stažený ZIP běží. Čeká na revizi a
  zveřejnění vlastníkem (GitHub → Releases → Draft → Publish). Teprve pak uvidí novou verzi kontrola
  aktualizací v aplikaci.
- Rozhodnutí vlastníka: log se nemaže ani po řádném ukončení (jen rotace).
- #10 registrace MCP, test na čistých Windows, ochranná známka, ukázka M4 + M5 + dnešních změn.

## 3. 11. 2026 – přejmenování na Clipcura, M5 (aplikace, tray, instalátor), nápověda a O aplikaci

### Hotovo

- **Přejmenování (rozhodnutí vlastníka, #19):** Clipsana koliduje s videoaplikací pro iPhone, nový název je
  **Clipcura**. Balíček, příkaz, exe, proměnné `CLIPCURA_*`, UI, instalátor, dokumentace. Repozitář je
  `Scoofer4/clipcura` (stará adresa přesměrovává). App data se jednou přesunou z `%APPDATA%\Clipsana`
  do `%APPDATA%\Clipcura` (ověřeno na notebooku vlastníka). Lokální složka je nově `D:\WorkspacePrg\Clipcura` (dříve `ClipsAna`).
- **#14 kvalita GPU kodérů:** NVENC bez `-maxrate` škrtil datový tok, takže zrnitý záznam ztrácel 1,1–1,2 VMAF
  proti libx264. Teď `-maxrate 200M`, H.264 profil High a `clipcura doctor` kalibruje CQ proti CPU kodéru
  (VMAF, tolerance 0,5). Tento notebook: všechny čtyři GPU kodéry drží kvalitu (`docs/benchmarks.md`).
- **#15 pravidlo `loudness`** jedním souborem (akceptace kap. 13); jen hlásí, oprava se zapíná v profilu.
  `social-30` a `ipad-light` měří proti −14 LUFS. Předtím obecná podpora nastavení pluginů v profilu.
- **M5:** `clipcura app` / `Clipcura.exe` = okno WebView2 + služba v procesu + ikona v oznamovací oblasti
  (průběh v logu, odznak pro žádosti AI, menu Otevřít/Pozastavit frontu/Ukončit, notifikace Windows).
  Pozastavení fronty (`/api/queue`). Instalátor: PyInstaller (Clipcura.exe + clipcura-cli.exe) a Inno Setup
  6.7.4 (nainstalován do `D:\WorkspacePrg\_innosetup`, cache PyInstalleru `D:\WorkspacePrg\_pyinstaller`).
  Instalace pro uživatele bez admin práv, EN/CS, kontrola WebView2, licence všech součástí.
- **Nápověda ke každé obrazovce** (tlačítko Nápověda vpravo nahoře, F1) a obrazovka **O aplikaci**
  (vlastník a tvůrce Metaverse Media s.r.o., autoři, licence, zdroj, všechny použité nástroje s verzí
  a licencí, plné licenční texty).
- Opravené chyby: #16 pád `doctor` v konzoli cp1250, #17 vypnutí služby viselo 30 s, #18 odinstalace
  nezavřela běžící aplikaci. Odstraněn `init_repo.ps1` (#2).

### Ověřeno

- pytest 228 prošlo / 2 přeskočeny, ruff OK, tsc OK, Playwright 11/11, CI zelené (fd10057).
- Na notebooku: okno, služba, ikona, dávka 4 převodů, zabalený MCP server připojený ke službě aplikace,
  instalace → upgrade přes běžící aplikaci → odinstalace přes běžící aplikaci (čisté).
- **Neověřeno:** vzhled notifikací a průběhu v ikoně (obrazovka byla zamčená), instalace na čistých
  Windows (Windows Sandbox není zapnutý), známková rešerše u ÚPV/EUIPO pro Clipcuru.

### Otevřené

- #10 registrace MCP v Claude Code: bezpečnostní kontrola Claude Code agentovi zápis do své konfigurace
  nepovolí, vlastník spustí příkaz z issue sám.
- Další krok: ukázka M4 + M5 vlastníkovi, test na čistých Windows, ochranná známka před vydáním.

## 3. 11. 2026 – M4 (MCP server + schvalování) – hotovo, čeká na ukázku vlastníkovi

### Hotovo

- `clipcura/mcp/server.py` (MCP SDK 2.3, `MCPServer`, stdio) a příkaz `clipcura mcp`. Je to tenký klient
  lokálního API a volá ho jako actor `ai`. Nástroje odpovídají kap. 8: `system_info`, `list_profiles`,
  `list_rules`, `scan_folder`, `get_report`, `plan_fixes`, `apply_fixes`, `job_status`, `cancel_job`.
  Nástroj pro schválení záměrně neexistuje. Odpovědi jsou strukturovaný JSON a krátké shrnutí (`lang` en/cs).
- Složka mimo whitelist: chyba s pokynem, ať ji povolí uživatel (AI povolené složky měnit nemůže).
- Když aplikace neběží, MCP spustí headless službu. Pod klientem v Node (tak MCP servery spouští
  Claude Code) služba ukončení MCP relace přežije, ověřeno. Klient MCP v Pythonu ji drží v job objektu
  Windows a zabije ji s relací. Proto vznikla:
- Obnova po pádu: úloha si pamatuje PID procesu, který ji vlastní (`jobs.owner_pid`). Nová služba po
  startu převezme jen úlohy mrtvého procesu: běžící úlohu restartuje a smaže její `.partial` soubor,
  čekající úlohu zařadí do fronty. Úlohy živého procesu (např. souběžné `clipcura apply`) nechá být.
  V časové ose je to akce „Obnoveno po restartu“ (actor `system`).
- Hromadné schválení/zamítnutí v GUI posílá požadavky souběžně (dřív postupně, mohlo zůstat napůl).
- Ukázka M4 na skutečné stdio relaci: AI udělá scan → report → plán → apply, 3 převody čekají v GUI,
  člověk schválí, převody doběhnou s odznakem AI. Screenshoty jsou v `docs/screenshots/m4/`.
- CI: e2e test dostal víc času; na runneru bez GPU se nefotí (software WebGL). Cesta k temp se
  rozlišuje na dlouhý tvar (runner má 8.3 `RUNNER~1`).

- #8: změna souběžnosti v Nastavení se projeví hned, bez restartu (worker mění počet slotů za běhu).
- #7: editor profilů v Nastavení (upravit, duplikovat, obnovit nebo smazat). Úprava vestavěného profilu
  vytvoří uživatelskou kopii v app data; vestavěný soubor zůstane nedotčen. Validace navíc proti schématu:
  kodek, kontejner (střihový kodek jen MOV/MKV), výstupní složka (absolutní jen uvnitř povolených), žádný
  výstup vedle originálu bez přípony, známá pravidla. Profily mění jen člověk.
- Měření pro akceptaci „s GPU je HEVC 10-bit měřitelně rychlejší“ je v `docs/benchmarks.md`
  (nástroj `tools/benchmark_hevc10.py`). Klip 4K HLG HEVC 10-bit, 10 s, na notebooku i7-9750H +
  GTX 1650 Max-Q: `social-30` CPU 17,5 s, GPU 9,6 s (1,82×); `ipad-light` CPU 20,6 s, GPU 10,7 s (1,93×).
- CI je znovu zelené (13b2771). Na runneru bez GPU běží UI testy po jednom a s omezeným pohybem,
  protože software WebGL zahlcovalo stránku (#11).

### Ověřeno

- pytest 191 prošlo / 1 přeskočen (skutečné vzorky), ruff OK, tsc OK, Playwright 10/10 lokálně i v režimu CI,
  CI na GitHubu: success (13b2771).

### Otevřené (issues)

- #10 otázka: zaregistrovat MCP v Claude Code? Je to konfigurace mimo repozitář, a tu podle pravidel
  bez souhlasu neměním. Příkaz je v README.
- #14 GPU enkodéry H.264: shoda kvality s libx264 není ověřená (NVENC píše profil Main).
- #15 pravidlo `loudness` (akceptace „nové pravidlo jedním souborem“): potřebuje cílovou hlasitost
  a rozhodnutí, zda jen hlásit, nebo i opravovat.
- #9 okno aplikace + tray + notifikace (M5), #1 #2 technický dluh.

## 2.–3. 11. 2026 – M3b (obrazovky 1–6) – hotovo

- API: GUI se servíruje ze stejného originu (SPA), historie skenů, audit, nastavení (mění jen člověk),
  náhledy před/po, seznam úloh.
- UI: token se předává ve fragmentu URL, živé události přes WebSocket, paleta Ctrl+K, obrazovky Start,
  Výsledek, Detail, Úlohy, Aktivita AI, Nastavení. Screenshoty v `docs/screenshots/m3b/`.
- Akceptace: celý cyklus jde projít jen klávesnicí (e2e test přes skutečný server v Edge).
- Otevřené: editor profilů s validací (zatím jen čtení), změna souběžnosti se projeví až po restartu,
  notifikace Windows a ikona v oznamovací oblasti patří do M5.

## 2. 11. 2026 – M3a (design system + /_kitchen-sink) – schváleno vlastníkem

Rozhodnutí: vizuální styl schválen, výchozí akcent **Brand** (Aurora zůstává jako volba), logo **Monogram**.
Další krok: M3b, tedy obrazovky 1–6 napojené na lokální API, paleta příkazů Ctrl+K, testy UI v CI.

### Hotovo

- `ui/`: React 18 + Vite + Tailwind 4 + Radix + Framer Motion + lucide + Recharts + i18next, three.js přes
  `@react-three/fiber` 8. Písma Inter a JetBrains Mono jsou přibalená lokálně. `npm` cache je na D:.
- Brand Metaverse Media v Confluence není, barvy jsou změřené z loga na metaversemedia.cz: karmínová
  `#e52c3f` / `#bf1b2c`, šedá `#d9d9d9`, doplňková korálová `#fe6c61`. (`#1863dc` z webu je barva cookie
  lišty, ne brand.)
- Přepínač akcentu Brand / Aurora, tmavé i světlé téma, angličtina a čeština, vypínač animací.
- 3D vizualizace podle požadavku vlastníka jsou funkční, ne dekorace (principy v `docs/design-system.md`):
  - vějíř políček v drop zóně se při přetažení srovná do zákrytu a kliknutím otevře výběr složky;
  - kadence VFR → CFR s volbou cílové frekvence a výpočtem, kolik snímků se vynechá nebo zopakuje;
  - kadenci běžící úlohy řídí počet zpracovaných snímků.
  3D běží na úsporné GPU a během převodu stojí.
- Funkční prototyp obrazovek 1–5 nad ukázkovými daty: karty filtrují tabulku, výběr klávesnicí, F opraví
  výběr, simulace úlohy, schválení nebo zamítnutí požadavku AI, dialog, oznámení.
- Logo: ze 4 konceptů vlastník vybral **Monogram**. Ostatní koncepty jsou z kódu odstraněné, zůstaly
  v historii gitu (commit `ca2a858`, screenshoty návrhu).
- Playwright přes nainstalovaný Edge (bez stahování prohlížeče): 6 testů, screenshoty v
  `docs/screenshots/m3a/`.

### Bezpečnostní poznámka (mimo Clipcuru)

- Některé stránky ve firemním prostoru Confluence obsahují čitelná hesla a klíče (stránky o PostgreSQL a n8n
  na Synology, Kurzy a vzdělání). Hodnoty se nikde neuvádějí. Doporučeno přesunout je do správce hesel.

## 2. 11. 2026 – M2 (lokální API, worker, WebSocket události) – hotovo

### Hotovo

- `core/config.py`: `config.json` v app data – token (vygeneruje se), port, povolené složky (výchozí žádná),
  schvalovací režim (výchozí zapnuto), souběžnost 1 GPU + 1 CPU. CLI `clipcura config show|allow|approval`
  (token se nikdy nevypisuje, jen maskovaný).
- `core/security.py`: whitelist složek po úplném rozlišení cesty (`..`, symlink i junction nevyskočí ven).
- `core/events.py` + `core/worker.py`: sběrnice událostí a worker se sloty GPU/CPU. `service.run_job` sdílí CLI
  i worker; nové `enqueue/approve/reject`, `cancel` umí i čekající úlohy. Stavy: awaiting_approval, queued,
  running, done, failed, cancelled, rejected.
- `api/app.py`: FastAPI jen na 127.0.0.1, bearer token, kontrola hlavičky Host (DNS rebinding), bez CORS.
  Endpointy kopírují nástroje MCP (system, profiles, rules, scans, plans, apply, jobs, cancel, approve,
  reject) + WebSocket `/api/events`. AI/n8n nesmí schvalovat. Výstupy plánu musí ležet v povolených složkách.
- `clipcura serve` (`api/server.py`) zapíše `server.json` (url, port, pid) pro GUI a MCP.
- Ukázka na skutečném serveru: AI naskenovala, naplánovala a požádala o převod → `awaiting_approval`,
  sama si schválit nemohla (403), člověk schválil, worker převedl, WebSocket přenesl všech 31 událostí.
- Testy: 158 prošlo. #5 a #6 uzavřené, commity `950f674`, `67b778e`, CI zelené.

### Další krok

- M3a: design system + `/_kitchen-sink` (React + Vite + Tailwind), schválení vzhledu Romanem screenshotem.
  Před instalací Node balíčků přesměrovat cache na D: (npm už je na `D:\WorkspacePrg\_npm`).

## 2. 11. 2026 – M1 (jádro, pravidla, profily, SQLite, CLI) – hotovo

### Hotovo

- `clipcura/core`: `probe` (barvy čte ze snímků, ne z kontejneru; hloubkový test VFR z PTS; kontrolní
  dekódování přes ffprobe), `profiles` (YAML + pydantic, uživatelské profily v app data mají přednost),
  `planner` (všechny opravy v **jednom** ffmpeg příkazu, slučování filtrů, CPU záloha), `executor` (průběh,
  dočasný soubor a atomické přejmenování, úklid při chybě nebo zrušení, kontrola místa), `db` (SQLite WAL,
  audit log), `service` = veřejné API `scan/plan/apply/status/cancel`.
- 11 pravidel jako pluginy (jeden soubor = jedno pravidlo, hlášky EN/CS): vfr, fps_mismatch, hdr,
  hevc_10bit, resolution, audio_rate, rotation, no_audio, insv, corrupt a **color_space** (BT.601 → Rec.709,
  jen když se soubor převádí kvůli jinému problému). Kritérium „nové pravidlo jedním souborem“ je ověřené.
- CLI: `scan`, `plan`, `apply`, `fix` (`--dry-run`, `--deep`, `--force`, `--json`). Návratové kódy 0/1/2.
- Orientace se zachovává (na výšku zůstává na výšku), limit rozlišení platí pro delší stranu.
- Testy: 112 prošlo (jednotkové + integrační na klipech z lavfi + reálné vzorky přes `CLIPCURA_REAL_DIR`).
  CI si stahuje ffmpeg s cache.
- Reálné vzorky z `data/` převedené přes CUDA za 3 min 17 s: CFR 30/1, DNxHR HQ, PCM 48 kHz, rotace
  fyzicky provedená, opakovaný běh nic nepřevádí. Synchronizace zvuku odpovídá originálu.
- Opravené chyby nalezené na reálných vzorcích: falešné „poškozeno“ u záznamu obrazovky, emoji ve výpisu
  příkazu, zavádějící varování o trhání u VFR z telefonu, nekonzistentní barevné značky (BT.601 snímky
  v kontejneru označeném BT.709).

- Doplněno po M1: #6 (minimum DNxHR v plánu), #5 (měření celých úloh v doctoru, výběr dekodéru
  cpu/cuda/d3d11va a scaleru, libplacebo tone-mapping kvůli kvalitě), oprava dekódování na Intelu (D3D11VA
  místo QSV) a barevných značek u zdrojů bez značek (`setparams`).

## 2. 11. 2026 – M0 (prostředí + `clipcura doctor`)

### Hotovo

- Veřejný repozitář <https://github.com/Scoofer4/clipcura>, první commit `20e020d` (kostra ze zadání).
  Commity se podepisují noreply identitou Scoofer4, nastavenou lokálně v repozitáři.
- Python 3.12.15 přes uv (`.python-version`), `uv sync --group dev`.
- `tools/fetch_ffmpeg.py` stáhne zafixovaný build BtbN ffmpeg **8.1** (`autobuild-2026-11-02-12-51`),
  ověří SHA-256 a uloží ho do `vendor/ffmpeg` i s `BUILD.json` (zdroj a licence pro instalátor).
- `clipcura doctor` (`--json`, `--quick`, `--path`) zjistí OS, CPU, RAM, disky a GPU
  (nvidia-smi + Windows adaptéry bez virtuálních). Funkčně otestuje ffmpeg: zařízení CUDA/QSV/Vulkan,
  HW dekódování HEVC 10-bit, enkodéry NVENC/QSV/x264/DNxHR/ProRes a filtry libplacebo/zscale.
  Vybere backend CUDA → QSV → CPU a report uloží do `doctor.json` v app data
  (`%APPDATA%\Clipcura`, přepíše ho `CLIPCURA_HOME`).
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
