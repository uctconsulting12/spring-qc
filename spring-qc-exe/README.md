# Spring QC — native Windows build

This folder packages the existing **spring-qc-app** (unmodified) as a native
Windows deployment matching the intended production architecture: **one
workstation/server** running the whole detection/tracking/API stack as a
background **Windows Service** (GPU-accelerated, always inferencing), and
**plain web browsers** on every other PC on the plant LAN — no client-side
app to install.

**Setting this up on-site, or just want to use it?** See
**[`GUIDE.md`](GUIDE.md)** — install through daily use, no dev background
needed. Everything below this point is for whoever builds/maintains this
packaging layer.

**Nothing about the product's own logic changes.** `app.py`, `detector.py`,
the database schema, the API, the web UI — all of it is used exactly as it
lives in `../spring-qc-app`, referenced from there at build time. This
folder is a packaging and lifecycle layer on top, not a fork. If you change
detection logic, fix a bug, or add a feature, you do it once in
`spring-qc-app` and rebuild here — there is no second copy to keep in sync.

## The three pieces

| | `server/` | `client-shortcuts/` | `hmi/` *(optional)* |
|---|---|---|---|
| Runs on | The one workstation with the GPU | Every other PC, as-is | A locked-down touch panel, if you have one |
| Is | A Windows Service | `.url` files (Desktop/Start Menu icons) | A native kiosk app |
| Installs | Python, PyTorch+CUDA, OpenCV, ultralytics, the whole app | Nothing — no install | A ~30&nbsp;MB WebView2 wrapper |
| Does | The actual detection/tracking/API/DB work, always on | Opens the default browser to the right page | Same, but full-screen and locked to one page |

**`server/` + `client-shortcuts/` is the deployment this was asked for**:
one box running the service, everyone else just opens a browser. `hmi/`
is an extra, only worth building if a specific operator panel needs to be
physically locked to one screen (no address bar, can't tab away, launches
on boot) — most sites won't need it; a browser shortcut is enough.

This mirrors the architecture already documented for the Docker deployment
(`../spring-qc-app/deploy/README.md`) — this is an alternative way to
*package* the same one-server-plus-browsers layout, for sites where a
native Windows install is preferred over Docker.

## `server/` — the inference box

* `springqc_launcher.py` — starts the app: resolves the database (bundled
  Postgres or an external one you point it at), checks and logs GPU
  availability, runs the existing FastAPI app with uvicorn, opens the admin
  page in a browser once it's ready.
* `springqc_service.py` — the same server wrapped as a real **Windows
  Service** (via pywin32), so it starts before anyone logs in and survives
  a reboot — the native-install equivalent of Docker's
  `restart: unless-stopped`.
* `springqc.spec` — PyInstaller build spec. Produces one bundle containing
  both `SpringQCServer.exe` (foreground/console, for first run) and
  `SpringQCService.exe` (the service).
* `springqc.ini` — runtime config: port, whether to bundle or point at an
  external Postgres. Lives next to the exe after install; edit it and
  restart, no rebuild needed.
* `build.bat` — one-command build. **Read the disk-space note below before
  running it.**
* `installer/SpringQC-Server.iss` — Inno Setup script producing a single
  `SpringQC-Server-Setup.exe` (installs to `C:\SpringQC\Server`, registers
  the service if the installer checkbox is ticked).

### The database

`app.py`'s own `init_db()` runs unmodified — it just needs `DATABASE_URL`
set correctly before the app module is imported, which the launcher does.
Two ways to run it, chosen by `springqc.ini`:

* **External Postgres** (recommended if a site already has one, or you're
  running several edge boxes against a shared server) — set `url =` in the
  `[database]` section.
* **Bundled Postgres** — leave `url` empty. The launcher runs `initdb` once
  and manages `pg_ctl start`/`stop` itself. This requires the portable
  PostgreSQL binaries to be present at `server/vendor/postgres/` at build
  time — **not included in this repo** (a ~180&nbsp;MB download); grab the
  "binaries zip" from
  [enterprisedb.com/download-postgresql-binaries](https://www.enterprisedb.com/download-postgresql-binaries)
  and extract its `pgsql/` folder there before building. Without it, the
  built exe requires an external `DATABASE_URL` and says so clearly in the
  log rather than failing silently.

### Disk space — read this before building

A CUDA-enabled PyTorch build needs roughly 15-20&nbsp;GB of scratch space
(the ~2.5&nbsp;GB torch wheel, its installed footprint, then PyInstaller's
own staging area). **`build.bat` builds entirely on a `BUILD_DRIVE` you set
at the top of the script (default `E:`), not the drive this repo lives
on** — specifically so it never risks filling your OS/dev drive. Point it at
whichever drive on your build machine actually has the room.

> While producing the first build of this project, the machine's C: and D:
> drives were both down to ~3&nbsp;GB free. Building there was correctly
> refused up front; a stray `pip` cache directory briefly wrote ~700&nbsp;MB
> to C: before being caught and redirected — both `pip`'s cache and its temp
> directory need pointing at the build drive too, not just PyInstaller's
> output, which `build.bat` now does (`--cache-dir`, `TEMP`/`TMP`). If you
> build on a drive that's already tight, verify free space before and during
> the PyTorch download, not just once at the start.

## `client-shortcuts/` — every other PC (the actual "HMI")

No install, no build, nothing to keep in sync with the server. Run
`install-shortcuts.bat` on the admin PC and any operator/monitor viewing
PC, enter the server's IP once, get Desktop icons ("Spring QC - Admin",
"- Operator", "- Monitor", "- Reports") that open in the default browser.
See `client-shortcuts/README.md`.

## `hmi/` — optional locked-down kiosk shell (not the default)

Only build this if a specific touch panel needs to be physically locked to
one screen — no address bar, can't navigate away, launches full-screen on
boot. For everything else, `client-shortcuts/` is simpler and is what "a
web client on the LAN" actually means.

* `springqc_hmi.py` — a native window (pywebview + Windows' built-in
  WebView2, not a bundled browser) that:
  - on first run, shows a small setup screen asking for the server's
    address and which screen to show (Operator / Admin / Monitor /
    Reports), saved to `%APPDATA%\SpringQC\hmi.json`;
  - otherwise goes straight full-screen to that page;
  - shows a friendly "reconnecting…" screen instead of a raw browser error
    if the edge box is booting or the network blips;
  - **Ctrl+Alt+S** reopens setup, **Ctrl+Alt+Q** exits to Windows — a
    global hotkey (not a JS shortcut on the page), so it works no matter
    which app screen is currently loaded.
* `springqc_hmi.spec` / `build.bat` — lightweight build, no GPU/ML
  dependencies at all.
* `installer/SpringQC-HMI.iss` — Inno Setup script with a "launch on
  startup" checkbox, for a panel that should come straight up in kiosk mode
  after a power cycle.

## What's actually been verified in this environment

Both executables were built for real and run against real hardware in this
session — not just written and assumed correct. **The server now runs
fully standalone: double-click `SpringQCServer.exe`, nothing else to
install, nothing else to configure.**

* **Server build, fully standalone (bundled Postgres + real GPU)** — a
  genuine GPU build: CUDA 12.4 PyTorch installed against this machine's
  real RTX A5000, portable PostgreSQL 16.10 binaries trimmed to just
  `bin/lib/share` (~123&nbsp;MB) and bundled into `vendor/postgres`, all run
  through `springqc.spec` → a 4.3&nbsp;GB `dist/SpringQCServer/`. Deleted
  `C:\ProgramData\SpringQC` first so this was a true first-run test — no
  Docker running, no `DATABASE_URL` set, nothing pre-configured — and
  double-clicked `SpringQCServer.exe`:
  ```
  First run: initializing bundled Postgres data directory at C:\ProgramData\SpringQC\pgdata
  Starting bundled Postgres on port 5433
  Using bundled Postgres at 127.0.0.1:5433
  GPU acceleration: ENABLED - NVIDIA RTX A5000 (22.5 GB VRAM, CUDA 12.4)
  Spring QC server starting on http://0.0.0.0:8099
  ```
  `initdb` → Postgres started → GPU detected → serving, in about 10 seconds,
  zero manual steps. `GET /admin` → `200`, `GET /operator` → `200`,
  `GET /gpu` → `{"available":true,"gpu_name":"NVIDIA RTX A5000","runs_on":"cuda"}`,
  `GET /operators` and `GET /reports/summary` both round-tripped the
  bundled database correctly.

  **Two real bugs were caught by this testing and fixed, not just found and
  noted:**
  1. The bundle directory resolved one level too high (`sys._MEIPASS` is
     already a directory in PyInstaller's onedir layout, unlike `__file__`
     in dev mode — taking `.parent` of it, as the first draft did, silently
     missed `springqc.ini`/`config.yaml`/etc.).
  2. `pg_ctl start` hung the launcher indefinitely on Windows the first time
     bundled Postgres was exercised: `subprocess.run(..., capture_output=True)`
     handed `pg_ctl` a pipe that a detached child `postgres.exe` process can
     end up holding open long after `pg_ctl` itself is done, so
     `subprocess.run` never saw EOF. Fixed by not capturing that call's
     output at all (`pg_ctl` already logs to its own `-l` file) — confirmed
     by re-running the exact same standalone test above, which went from
     hanging forever to fully up in ~10 seconds.

  Console-output logic was also fixed: it was keying off "is this frozen at
  all" instead of "is this the console exe specifically," which would have
  silently swallowed `SpringQCServer.exe`'s on-screen log output in
  production.

* **HMI kiosk build** — built end-to-end with PyInstaller, produced a real
  ~29&nbsp;MB `SpringQCHMI.exe`, launched it once, confirmed it opens a
  genuine WebView2 window, then rebuilt against the pinned
  `pywebview==4.4.1` (a long-stable release, in place of the interop issues
  a newer version showed against this machine's WebView2/.NET runtime).
  **Not re-launched after that rebuild** — a full-screen app took over the
  screen unannounced the first time, which shouldn't have happened; verify
  it visually yourself before rolling it out, the same way you'd check any
  kiosk image before deploying it.

All builds happened on `E:\SpringQC-Build*`, never on the source drive; the
live Docker stack (`spring-qc-app-app-1` / `-db-1`) and its real data were
never touched by any of this — every server verification ran against a
disposable database on a different port, and the plain server build's
Windows Service was never installed on this machine. All test data
(`C:\ProgramData\SpringQC`, the throwaway Postgres containers) was deleted
afterward — the built exe's own first-run experience is exactly what was
just tested.

To reproduce a build yourself: `server/build.bat` / `hmi/build.bat` (point
`BUILD_DRIVE` at a disk with room), then `installer/build_installer.bat` in
each folder (needs [Inno Setup 6](https://jrsoftware.org/isdl.php), not
installed in this session) for a proper single-file `Setup.exe`. Until then,
`E:\SpringQC-Build\dist\SpringQCServer\SpringQCServer.exe` and
`E:\SpringQC-Build-HMI\dist\SpringQCHMI\SpringQCHMI.exe` are ready to run
directly, portable-app style.

## Deploying

1. Run `SpringQC-Server-Setup.exe` on the **one workstation** with the GPU.
   Tick "install the service" — this is what keeps it inferencing in the
   background, no one logged in, survives a reboot.
2. On the admin PC and every other viewing PC: run
   `client-shortcuts\install-shortcuts.bat`, enter that workstation's IP.
   Done — Desktop icons open Admin/Operator/Monitor/Reports in whatever
   browser is already installed.
3. Only for a touch panel that must be locked to one screen: build and
   install `SpringQC-HMI-Setup.exe` there instead of a browser shortcut.
4. Everything else — operators, ROI, settings, reports — works exactly as
   documented in `../spring-qc-app/README.md`, because it's the same app.
