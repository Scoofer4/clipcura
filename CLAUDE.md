# Clipsana – zadání pro realizaci (v0.3)

Vydává Metaverse Media s.r.o. jako open source (Apache-2.0) · Vlastník: Roman · Realizace: Claude Code na Romanově notebooku · Stav: k zahájení
Zdroj pravdy: interní zadání Metaverse Media s.r.o. „Zadání: Clipsana“. Tento soubor je jeho kopie pro repozitář.

## 1. Cíl

Windows aplikace, která zkontroluje videa ze všech zdrojů (Samsung S21FE, Insta360, Sony A6400, screen recording) a automaticky opraví vlastnosti, kvůli kterým **padá DaVinci Resolve**: proměnná snímková frekvence (VFR), rozdílné fps a rozlišení, HDR, HEVC 10-bit, zvuk mimo 48 kHz. Dnes se to řeší ručně v Shutter Encoderu, který pády spolehlivě odstraňuje. Clipsana má tento převod automatizovat.

Ovládá ji **člověk přes GUI** a **AI přes MCP**. Obojí volá stejné jádro, AI nemá žádné schopnosti navíc. Běží lokálně a využívá GPU.

**Klíčový požadavek vlastníka: krásné UX, skoro high-tech UI.** Vizuální kvalita je akceptační kritérium, ne bonus.

## 2. Pevná rozhodnutí

1. Žádné vlastní kodeky ani filtry. Zpracování dělá ověřený **ffmpeg/ffprobe**; aplikace rozhoduje, co a jak opravit.
2. Jedno jádro, rozhraní: GUI, MCP, CLI (+ lokální HTTP API, které používá GUI a později n8n).
3. Originály jsou vždy jen pro čtení. Zápis jen do výstupní složky.
4. Shutter Encoder zůstává ruční záloha.
5. **Open source:** licence Apache-2.0, veřejný repozitář na GitHubu, volně šiřitelné. Kód, komentáře, README a výchozí jazyk UI anglicky; čeština jako překlad. Zadání (`CLAUDE.md`) zůstává česky.

## 3. Architektura

```
 GUI (React v okně pywebview/WebView2) ──┐
 n8n (později) ──────────────────────────┼──► lokální API (FastAPI, 127.0.0.1, token, WebSocket události)
 MCP server (stdio, tenký klient) ───────┘                       │
 CLI ───────────────────────────────────────────────────────────►│
                                                                  ▼
                 JÁDRO clipsana.core: probe → pravidla → plán → fronta úloh → worker → report
                                     SQLite (WAL): soubory, nálezy, plány, úlohy, audit log
                                                                  │
                                              ffmpeg / ffprobe (přibalený build)
```

- **Jádro** (`clipsana/core`): čistá knihovna bez UI, veřejné API `scan()`, `plan()`, `apply()`, `status()`, `cancel()`.
- **Worker** běží v procesu aplikace (nebo headless `clipsana serve`). Souběžnost konfigurovatelná, výchozí 1 GPU + 1 CPU úloha.
- **Lokální API** (`clipsana/api`): FastAPI na `127.0.0.1`, náhodný port, bearer token uložený v `%APPDATA%\Clipsana\config.json`. WebSocket kanál pro průběh úloh a události (včetně akcí AI).
- **MCP server** (`clipsana/mcp`): FastMCP, transport stdio. Volá lokální API; když aplikace neběží, spustí headless server.
- **GUI** (`ui/`): React + TypeScript, build do statických souborů, servíruje je API a zobrazuje okno **pywebview** (Edge WebView2, je součástí Windows 10/11).
- **CLI** (`clipsana` příkaz): `scan`, `plan`, `apply`, `serve`, `doctor`.

### Proč webové UI místo PySide6 (změna proti v0.1)
High-tech vzhled (animace, sklo, glow, plynulé grafy) se ve webovém stacku dělá výrazně lépe a rychleji než v Qt Widgets. API, které UI potřebuje, zároveň poslouží n8n. pywebview zachová jednu Python aplikaci a balení přes PyInstaller.

## 4. Technologie

| Oblast | Volba |
|---|---|
| Jazyk jádra | Python 3.12, správa prostředí `uv` |
| Média | ffmpeg/ffprobe 8.1 (řada 7.x už v BtbN není; rozhodnutí vlastníka 2. 11. 2026) **redistribuovatelný GPL build bez „nonfree“** pro Windows (např. BtbN `win64-gpl`) s NVENC/NVDEC, QSV, zscale, libplacebo |
| API | FastAPI + uvicorn, pydantic v2 |
| Data | SQLite (WAL), profily YAML |
| MCP | oficiální MCP Python SDK (FastMCP), stdio |
| UI | React 18 + TypeScript + Vite + Tailwind CSS, Radix UI primitiva, Framer Motion, lucide-react ikony, Recharts |
| Okno | pywebview (WebView2) |
| GPU telemetrie | `nvidia-smi` (NVIDIA), jinak jen stav enkodérů z ffmpeg |
| Testy | pytest, testovací klipy generované přes ffmpeg lavfi, Playwright pro UI smoke testy |
| Balení | PyInstaller (onedir) + Inno Setup instalátor |

Fonty (Inter, JetBrains Mono) přibalit lokálně, žádné CDN. ffmpeg se šíří jako samostatný program vedle aplikace (volání přes subprocess), takže licence Apache-2.0 naší aplikace je v pořádku. Šířit smí jen build **bez nonfree** částí: `scale_cuda` a libnpp v něm nejsou, škálování na GPU proto přes **libplacebo**. Instalátor musí obsahovat licenci ffmpeg (GPL) a odkaz na odpovídající zdrojový kód. Ověřit u konkrétního buildu před vydáním.

## 5. Cílový stroj: notebook – nejdřív ověřit

Realizace a první provoz jsou na Romanově notebooku (HW ověřit). **První krok M0 je `clipsana doctor`**, který zjistí a uloží:
- GPU a ovladač (`nvidia-smi`, případně Intel iGPU),
- `ffmpeg -hwaccels`, dostupné enkodéry (`h264_nvenc`, `hevc_nvenc`, `h264_qsv`, `hevc_qsv`) a filtry (`libplacebo`, `zscale`, `scale_qsv`),
- volné místo, RAM, CPU.

Backendy akcelerace v pořadí: **CUDA/NVENC → Intel QSV → CPU**. Aplikace musí plně fungovat i na CPU. Výběr backendu ukazuje GUI.

## 6. Pravidla (pluginy)

Každá kontrola je soubor v `clipsana/rules/`, registrace přes entry point nebo auto-discovery. Nové pravidlo nesmí vyžadovat změnu jádra.

```python
@dataclass
class Issue:
    rule_id: str          # "vfr"
    severity: str         # "info" | "warning" | "error" (error = Resolve pravděpodobně spadne)
    message: str          # lokalizovaně (EN/CZ), srozumitelně pro člověka i AI
    auto_fixable: bool
    data: dict            # naměřené hodnoty

@dataclass
class FixStep:
    order: int            # pořadí ve filtrech: rotace < HDR < scale < fps
    video_filters: list[str]
    audio_filters: list[str]
    output_args: list[str]
    gpu_variant: dict[str, list[str]] | None = None   # {"cuda": [...], "qsv": [...]}

class Rule(Protocol):
    id: str
    title: str
    def detect(self, media: MediaInfo, profile: Profile) -> Issue | None: ...
    def fix(self, issue: Issue, profile: Profile) -> FixStep | None: ...
```

Planner spojí kroky jednoho souboru do **jediného** ffmpeg příkazu. ffmpeg se volá výhradně seznamem argumentů, nikdy přes shell.

| ID | Detekce | Oprava | Auto |
|---|---|---|---|
| `vfr` | `r_frame_rate` ≠ `avg_frame_rate` (tolerance 1 %); volitelně hluboký test rozestupů PTS | `fps` filtr + `-fps_mode cfr`, zvuk `aresample=48000:async=1:first_pts=0` | ano |
| `fps_mismatch` | fps ≠ profil | převod na cílové fps; varování u 24/25 → 30 | ano |
| `hdr` | `color_transfer` smpte2084 / arib-std-b67 | tone-mapping do Rec.709 (libplacebo, jinak zscale + tonemap) | ano |
| `hevc_10bit` | HEVC + 10bit pix_fmt | převod do střihového kodeku | ano |
| `resolution` | delší strana > limit, liché rozměry | zmenšení se zachováním poměru, sudé rozměry | ano |
| `audio_rate` | zvuk ≠ 48 kHz | převzorkování | ano |
| `rotation` | metadata rotace | fyzické otočení, smazání metadat | ano |
| `no_audio` | chybí zvuk | volitelně tichá stopa | ano |
| `insv` | `.insv`, `.insp` | jen hlášení „exportovat v Insta360 Studio“ | ne |
| `corrupt` | ffprobe selže, nulová délka, chyba dekódování vzorku | jen hlášení | ne |

Prototyp `mm_video_prep.py` (otestovaný na VFR, 60 fps, HLG HEVC 10-bit, 44,1 kHz) je referenční implementace prvních pravidel.

**Referenční recept:** nastavení, kterým Shutter Encoder pády opravoval, doplní Roman. Výchozí profil ho má reprodukovat.

## 7. Profily

```yaml
# profiles/social-30.yaml
name: social-30
label: "Sociální sítě · 30 fps"
fps: 30
max_long_side: 3840
audio_rate: 48000
color: rec709-sdr
output:
  codec: dnxhr_hq        # dnxhr_hq | dnxhr_hqx | prores_422 | h264_nvenc | hevc_nvenc | h264_qsv | libx264
  container: mov
  folder: "../02_edit"
  suffix: "_edit"
rules:
  disabled: []
  vfr_deep_check: false
```

Další: `ipad-light` (H.264, 1080p, GPU enkodér dle dostupnosti), `hero-10bit` (DNxHR HQX, bez zmenšení). DNxHR/ProRes nemají GPU enkodér; GPU pomáhá s dekódováním a filtry.

## 8. MCP nástroje

Kopírují akce v GUI. Odpovědi = strukturovaný JSON + krátké shrnutí v jazyce uživatele.

| Nástroj | Parametry | Vrací | Mění data |
|---|---|---|---|
| `system_info` | – | backend, GPU, enkodéry, volné místo | ne |
| `list_profiles`, `list_rules` | – | seznam s popisy | ne |
| `scan_folder` | path, profile, recursive, deep | scan_id, souhrn | jen DB |
| `get_report` | scan_id, filtr | soubory, nálezy, hodnoty | ne |
| `plan_fixes` | scan_id, file_ids? | plán, odhad času a velikosti, ffmpeg příkazy | ne |
| `apply_fixes` | plan_id | job_ids; ve schvalovacím režimu `awaiting_approval` | ano (výstupní složka) |
| `job_status` | job_ids | průběh, chyby, výstupy | ne |
| `cancel_job` | job_id | stav | ano |

## 9. UX a UI – high-tech, ale srozumitelné

### Principy
1. **Jedna hlavní akce na obrazovce.** Přetáhni složku → vidíš stav → jedním klikem opravíš.
2. **Technika pod kapotou, ale na dosah.** Výchozí pohled mluví lidsky („Proměnná snímková frekvence – Resolve může spadnout“), detail ukáže čísla a ffmpeg příkaz.
3. **Živý systém.** Všechno, co se děje (i to, co dělá AI), je vidět v reálném čase.
4. **Rychlost je součást designu.** Okamžitá odezva, skeleton stavy, žádné zamrzlé okno.

### Vizuální jazyk
- **Tmavé téma jako výchozí** (světlé volitelně): pozadí grafit/téměř černá s jemným šumem a radiálním přechodem, panely jako „sklo“ (průhlednost + blur + tenký světlý okraj).
- **Akcent:** elektrická fialová → azurová (gradient) pro hlavní akce a průběh; stavové barvy: OK zelená, opravitelné ambrová, vyžaduje člověka oranžová, chyba červená. Všechny barvy jako design tokeny (CSS proměnné), aby šly sladit s brandem.
- **Typografie:** Inter pro text, JetBrains Mono pro technické hodnoty (fps, kodeky, cesty).
- **Pohyb:** Framer Motion, krátké (150–250 ms) a funkční animace: glow drop zóny při přetažení, plynulé přeskupení řádků při změně stavu, „pulz“ aktivní úlohy. Respektovat `prefers-reduced-motion` a přepínač v nastavení.
- **Kontrast** min. WCAG AA, ovládání klávesnicí, viditelný focus.

### Obrazovky
1. **Dashboard / Drop zóna:** velká animovaná zóna „Přetáhni složku s videi“, poslední složky, volba profilu (segmentovaný přepínač), stav systému (backend CPU/CUDA/QSV, GPU vytížení, volné místo) jako kompaktní „HUD“ panel.
2. **Výsledek kontroly:** souhrnné karty (OK / opravitelné / vyžaduje člověka / chyby) + tabulka souborů s náhledovým snímkem, čipy nálezů, klíčovými parametry (rozlišení, fps r/avg, kodek, HDR, zvuk). Filtrování, hromadný výběr, tlačítko **Opravit vybrané** s odhadem času a místa.
3. **Detail souboru (boční panel):** naměřené hodnoty, nálezy s vysvětlením „proč to vadí Resolve“, náhled **před/po** se svislým posuvníkem (snímky z ffmpeg ve stejném čase), plánovaný ffmpeg příkaz s tlačítkem kopírovat.
4. **Fronta úloh:** živé karty s průběhem (%, fps zpracování, zbývající čas), mini graf rychlosti, zrušení. Úlohy od AI označené odznakem „AI“.
5. **AI aktivita a schvalování:** časová osa akcí přes MCP (sken, plán, žádost o spuštění). Žádosti ve stavu `awaiting_approval` jako výrazné karty s tlačítky **Schválit / Zamítnout** a shrnutím, co se stane.
6. **Nastavení:** profily (editor s validací), backend akcelerace, souběžnost, povolené složky (whitelist), schvalovací režim, cesta k ffmpeg, téma, animace.

### Interakce navíc
- **Paleta příkazů** `Ctrl+K` (otevřít složku, přepnout profil, opravit vše, přejít na frontu).
- Klávesové zkratky v tabulce (mezerník výběr, `Enter` detail, `F` opravit).
- **Toasty** a systémová notifikace Windows po dokončení dávky; ikona v oznamovací oblasti s průběhem.
- Prázdné a chybové stavy navržené stejně pečlivě jako šťastná cesta (srozumitelná zpráva + další krok).
- UI anglicky jako výchozí, čeština jako druhý jazyk; všechny texty v i18n souborech.

### Postup návrhu
Nejdřív **design system** (tokeny, typografie, komponenty: tlačítka, čipy, karty, tabulka, progress, toast, modal) na stránce `/_kitchen-sink`, schválení Romanem screenshotem, teprve pak obrazovky. Každá obrazovka se odevzdává se screenshotem v tmavém i světlém tématu.

## 10. Bezpečnost

- Originály read-only, zápis jen do výstupní složky; žádná akce neumí mazat ani přepisovat originály.
- Whitelist kořenových složek; API i MCP odmítnou cesty mimo něj (kontrola po normalizaci cesty, ochrana proti `..` a symlinkům).
- API jen na `127.0.0.1`, bearer token, žádné CORS mimo vlastní origin.
- Schvalovací režim pro AI výchozí **zapnuto**.
- Audit log: kdo (human/ai/n8n), kdy, co, výsledek.
- Kontrola volného místa před spuštěním (odhad velikosti výstupu), přerušená úloha smaže neúplný výstup.

## 11. Struktura repozitáře

```
clipsana/
  core/        probe.py, models.py, planner.py, executor.py, worker.py, db.py, profiles.py, backends.py
  rules/       vfr.py, fps_mismatch.py, hdr.py, hevc_10bit.py, resolution.py, audio_rate.py, rotation.py, no_audio.py, insv.py, corrupt.py
  api/         app.py, routes/, events.py (WebSocket)
  mcp/         server.py
  cli.py
  app.py       spuštění okna pywebview + API + worker + tray
profiles/      social-30.yaml, ipad-light.yaml, hero-10bit.yaml
ui/            React aplikace (src/components, src/screens, src/design-system, src/i18n)
tests/         unit + integrační testy s generovanými klipy, fixtures/real/ (skutečné vzorky, mimo git)
packaging/     pyinstaller.spec, installer.iss
docs/          screenshoty, poznámky k vydání
```

## 12. Milníky (každý končí ukázkou Romanovi)

| # | Obsah | Hotovo, když |
|---|---|---|
| M0 | Prostředí: git, uv, Node, ffmpeg build, `clipsana doctor` | doctor vypíše HW a schopnosti ffmpeg na notebooku |
| M1 | Jádro, pravidla, profily, SQLite, CLI, testy | všechna pravidla projdou testy na generovaných klipech; CLI opraví složku |
| M2 | Lokální API + worker + WebSocket události | průběh úlohy jde sledovat přes API |
| M3a | Design system + kitchen sink | Roman schválí vizuální styl |
| M3b | Obrazovky 1–6 | celý cyklus jde udělat jen myší i jen klávesnicí |
| M4 | MCP server + schvalování | Claude přes MCP projde scan → plan → apply → status, úloha čeká na schválení v GUI |
| M5 | Instalátor + ikona v oznamovací oblasti | instalace na čistých Windows jedním souborem |

## 13. Akceptační kritéria

- [ ] Každé pravidlo správně detekuje a opraví testovací klip (VFR, 24/25/60 fps, HLG, PQ, HEVC 10-bit, 6K, liché rozměry, 44,1 kHz, rotace); výstup ověřen přes ffprobe.
- [ ] Opravené soubory ze skutečných zdrojů (S21FE, Insta360 export, A6400, screen recording, včetně těch, na kterých Resolve padal) se v DaVinci Resolve importují a stříhají bez pádu a bez posunu zvuku.
- [ ] Výsledek pro „problémové“ soubory je minimálně stejně stabilní v Resolve jako převod ze Shutter Encoderu.
- [ ] Opakované spuštění nepřevádí hotové soubory.
- [ ] GUI a MCP současně vidí stejné úlohy; akce AI jsou v GUI vidět živě.
- [ ] Nové pravidlo jde přidat jedním souborem (ověřit na `loudness`).
- [ ] Aplikace funguje na CPU; s GPU je u HEVC 10-bit měřitelně rychlejší (změřit a zapsat do docs).
- [ ] UI: tmavé i světlé téma, plynulé animace bez sekání, WCAG AA kontrast, ovládání klávesnicí, Roman schválil vzhled.
- [ ] Instalátor na čistých Windows včetně ffmpeg.

## 14. Pravidla pro práci v Claude Code

- Před každým milníkem krátký plán, po něm ukázka a commit. Malé commity s anglickými popisy (veřejný repozitář).
- Testy píšu před opravou chyby (reprodukce → oprava).
- Kód s komentáři vysvětlujícími „proč“, ne „co“.
- Neinstalovat nic globálně bez souhlasu; ffmpeg do `vendor/ffmpeg/`.
- Skutečné vzorky videí nikdy do gitu (`tests/fixtures/real/` v `.gitignore`).
- Repozitář je veřejný: žádné firemní údaje, tokeny, interní adresy ani klientská videa v kódu, testech ani historii commitů.
- „DaVinci Resolve“ jen popisně, bez loga a bez „Resolve“ v názvech.
- Nic, co by mazalo nebo přepisovalo soubory mimo výstupní složku, ani v testech.

## 15. Co potřebuji od Romana před startem

- [ ] Nastavení Shutter Encoderu, které pády opravovalo (funkce, kodek, fps, rozlišení).
- [ ] 5–10 skutečných vzorků z každého zařízení, ideálně i soubory, na kterých Resolve padal.
- [ ] Verze DaVinci Resolve (Studio nebo free).
- [ ] Souhlas se stažením ffmpeg buildu, Node.js a uv; pod jakým GitHub účtem/organizací založit veřejný repozitář.
- [ ] Barvy brandu Metaverse Media, pokud má být akcent sladěný.
- [ ] Ověření jména Clipsana: ochranná známka (EUIPO, ÚPV, třída 9) a doména (.app / .dev). PyPI a npm jsou k 2. 11. 2026 volné, repozitář tohoto jména na GitHubu neexistuje.
