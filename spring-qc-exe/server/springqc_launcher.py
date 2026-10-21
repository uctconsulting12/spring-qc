"""
Spring QC Server - production launcher.

This is a *packaging and lifecycle* layer only. It does not contain, fork, or
re-implement any detection/tracking/API logic - it imports the existing
`app.py` from spring-qc-app unmodified and runs it with uvicorn. That keeps
exactly one source of truth for the product's actual behaviour; this file's
only job is to make that behaviour boot reliably as a standalone Windows
executable / service on an industrial PC:

    1. Resolve where the app's own files live (source checkout in dev,
       PyInstaller's bundle directory when frozen).
    2. Resolve a database - either an operator-configured external Postgres
       (DATABASE_URL), or a bundled portable Postgres instance under
       vendor/postgres, started and stopped by this launcher.
    3. Verify GPU acceleration is actually available and log it loudly either
       way - an inference server that silently fell back to CPU on a factory
       floor is a support incident waiting to happen.
    4. Run the FastAPI app with uvicorn.Server (not the blocking
       `uvicorn.run` helper) so a Windows Service wrapper can ask it to stop
       cleanly instead of killing the process.
    5. Open the admin page in the default browser once the server is ready,
       for the plain double-click / foreground use case.

Configuration is read from `springqc.ini` next to this launcher (or next to
the frozen .exe), with environment variables as overrides - so the same
build can be pointed at a bundled DB on one machine and a shared external
Postgres on another, without a rebuild.
"""
from __future__ import annotations

import configparser
import logging
import logging.handlers
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# --------------------------------------------------------------------------
# Path resolution: dev checkout vs. frozen (PyInstaller onedir) bundle.
# --------------------------------------------------------------------------

FROZEN = bool(getattr(sys, "frozen", False))

# Where this launcher's own files (and, once built, the bundled app + vendor
# folders) live. sys._MEIPASS is ALREADY a directory (PyInstaller >= 6's
# onedir layout: <exe dir>\_internal), unlike __file__ in dev mode - taking
# .parent of it too (as an earlier version of this file did) silently climbs
# one level too high and the bundle's data files (springqc.ini, config.yaml,
# static/, model/, trackers/) stop being found. Caught by an actual frozen
# run, not just by reading the code - see the build notes in ../README.md.
if FROZEN:
    LAUNCHER_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    LAUNCHER_DIR = Path(__file__).resolve().parent

# The actual Spring QC application (app.py, detector.py, static/, model/,
# config.yaml, trackers/) is bundled at the root of this same folder by the
# PyInstaller spec (see springqc.spec) - or, in dev mode (running this file
# directly with `python`), lives in the sibling spring-qc-app checkout, so
# you can iterate on the launcher without rebuilding the exe every time.
if FROZEN:
    APP_DIR = LAUNCHER_DIR
else:
    APP_DIR = (LAUNCHER_DIR / ".." / ".." / "spring-qc-app").resolve()

VENDOR_DIR = LAUNCHER_DIR / "vendor"
PG_HOME = VENDOR_DIR / "postgres"
PG_BIN = PG_HOME / "bin"

# All mutable state (database files, logs, config edits made from the
# Settings panel) lives outside the install folder so the service can run
# under LocalSystem and a non-admin operator can still be handed the
# machine without Program-Files permission headaches. This mirrors exactly
# what the Docker deployment gives you for free via named volumes.
DATA_ROOT = Path(os.environ.get("SPRINGQC_DATA_DIR", r"C:\ProgramData\SpringQC"))
LOG_DIR = DATA_ROOT / "logs"
PGDATA_DIR = DATA_ROOT / "pgdata"

log = logging.getLogger("springqc.launcher")


def _setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "server.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # SpringQCServer.exe is built with console=True specifically so a
    # foreground/first-run user sees log output on screen; SpringQCService.exe
    # (console=False) has no console to write to and would just raise on a
    # missing stdout, and in dev mode sys.executable is plain python(.exe).
    # Checking the frozen executable's own name (rather than just "are we
    # frozen at all") is what actually distinguishes the two built exes.
    exe_name = Path(sys.executable).stem.lower() if FROZEN else ""
    wants_console = (not FROZEN) or exe_name == "springqcserver" or os.environ.get("SPRINGQC_CONSOLE")
    if wants_console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["server"] = {"host": "0.0.0.0", "port": "8001", "open_browser": "true", "browser_page": "/admin"}
    cfg["database"] = {"mode": "auto", "url": "", "bundled_port": "5433"}
    ini_path = LAUNCHER_DIR / "springqc.ini"
    if ini_path.exists():
        cfg.read(ini_path, encoding="utf-8")
    else:
        log.info("No springqc.ini found at %s - using defaults", ini_path)
    return cfg


# --------------------------------------------------------------------------
# GPU acceleration check - the whole point of running this on real hardware
# instead of a generic cloud box. We never hide a CPU fallback: an operator
# station that's silently 10x slower than expected is exactly the kind of
# thing that should show up in the log the moment it happens, not get
# discovered when RTSP starts dropping frames three shifts later.
# --------------------------------------------------------------------------

def check_gpu() -> str:
    try:
        import torch  # imported lazily so this file stays importable even
                       # before the environment/venv has torch installed.
    except ImportError:
        log.error("PyTorch is not installed in this environment - inference cannot run at all.")
        return "unavailable"

    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        log.info("GPU acceleration: ENABLED - %s (%.1f GB VRAM, CUDA %s)", name, vram_gb, torch.version.cuda)
        return "cuda"

    log.warning(
        "GPU acceleration: NOT AVAILABLE - no CUDA device detected. Falling back to CPU inference. "
        "This will not keep up with a live RTSP stream under load; check the NVIDIA driver and that "
        "this build was produced with a CUDA-enabled PyTorch (see server/build.bat)."
    )
    return "cpu"


# --------------------------------------------------------------------------
# Bundled Postgres lifecycle (only used when no external DATABASE_URL is
# configured). Entirely optional: an admin who already runs a shared
# Postgres for the site just points springqc.ini / DATABASE_URL at it and
# none of this code path executes.
# --------------------------------------------------------------------------

class BundledPostgres:
    def __init__(self, port: int):
        self.port = port
        self._proc_started = False

    @property
    def available(self) -> bool:
        return (PG_BIN / "pg_ctl.exe").exists()

    @property
    def url(self) -> str:
        return f"postgresql://spring_qc:spring_qc@127.0.0.1:{self.port}/spring_qc"

    def ensure_running(self) -> None:
        if not self.available:
            raise RuntimeError(
                f"No external DATABASE_URL is configured, and no bundled Postgres was found at "
                f"{PG_BIN}. Either set DATABASE_URL in springqc.ini / the environment to point at "
                f"an existing PostgreSQL server, or populate vendor/postgres with the portable "
                f"PostgreSQL binaries before building (see server/build.bat)."
            )
        PGDATA_DIR.parent.mkdir(parents=True, exist_ok=True)
        if not (PGDATA_DIR / "PG_VERSION").exists():
            log.info("First run: initializing bundled Postgres data directory at %s", PGDATA_DIR)
            subprocess.run(
                [str(PG_BIN / "initdb.exe"), "-D", str(PGDATA_DIR), "-U", "spring_qc",
                 "-A", "trust", "-E", "UTF8"],
                check=True, capture_output=True, text=True, timeout=60,
            )
        log.info("Starting bundled Postgres on port %s", self.port)
        # IMPORTANT: not capture_output here. `pg_ctl start` on Windows spawns
        # postgres.exe as a background process that can inherit pg_ctl's own
        # stdout/stderr handles; if we hand pg_ctl a PIPE (what
        # capture_output=True does), that inherited handle can stay open in
        # the detached postgres process long after pg_ctl itself is done,
        # and subprocess.run then blocks forever waiting for EOF on a pipe
        # nothing is ever going to close. pg_ctl already writes everything
        # useful to the `-l` logfile, so nothing is lost by not capturing.
        subprocess.run(
            [str(PG_BIN / "pg_ctl.exe"), "-D", str(PGDATA_DIR),
             "-l", str(LOG_DIR / "postgres.log"),
             "-o", f'-p {self.port} -c listen_addresses=127.0.0.1',
             "start"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        self._proc_started = True
        self._wait_ready()
        self._ensure_role_and_db()

    def _wait_ready(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(
                [str(PG_BIN / "pg_isready.exe"), "-h", "127.0.0.1", "-p", str(self.port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
            if r.returncode == 0:
                return
            time.sleep(0.5)
        raise RuntimeError("Bundled Postgres did not become ready in time - see logs/postgres.log")

    def _ensure_role_and_db(self) -> None:
        # initdb with -U spring_qc already created that superuser; the
        # spring_qc database itself still needs creating on a fresh cluster.
        subprocess.run(
            [str(PG_BIN / "createdb.exe"), "-h", "127.0.0.1", "-p", str(self.port),
             "-U", "spring_qc", "spring_qc"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
            # non-zero exit here just means the database already exists - fine
        )

    def stop(self) -> None:
        if self._proc_started and self.available:
            log.info("Stopping bundled Postgres")
            subprocess.run(
                [str(PG_BIN / "pg_ctl.exe"), "-D", str(PGDATA_DIR), "stop", "-m", "fast"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )


def resolve_database_url(cfg: configparser.ConfigParser) -> tuple[str, BundledPostgres | None]:
    env_url = os.environ.get("DATABASE_URL")
    ini_url = cfg.get("database", "url", fallback="").strip()
    if env_url:
        log.info("Using DATABASE_URL from environment (external database)")
        return env_url, None
    if ini_url:
        log.info("Using database URL from springqc.ini (external database)")
        return ini_url, None

    port = cfg.getint("database", "bundled_port", fallback=5433)
    bundled = BundledPostgres(port)
    bundled.ensure_running()
    log.info("Using bundled Postgres at 127.0.0.1:%s", port)
    return bundled.url, bundled


# --------------------------------------------------------------------------
# Server orchestration
# --------------------------------------------------------------------------

class SpringQCServer:
    """Owns the uvicorn.Server instance so a caller (console main, or the
    Windows Service wrapper) can start it non-blocking and stop it cleanly."""

    def __init__(self):
        self.cfg = _load_config()
        self._uvicorn_server = None
        self._pg: BundledPostgres | None = None
        self._thread: threading.Thread | None = None

    def start(self, *, open_browser: bool | None = None) -> None:
        import uvicorn

        db_url, pg = resolve_database_url(self.cfg)
        self._pg = pg
        os.environ["DATABASE_URL"] = db_url

        check_gpu()

        # Importing the app module triggers its own init_db() - by this
        # point DATABASE_URL is guaranteed correct, so that succeeds.
        sys.path.insert(0, str(APP_DIR))
        os.chdir(APP_DIR)  # config.yaml / uploads / Output are resolved
                            # relative to the app's own BASE_DIR, not cwd,
                            # but running from here keeps relative log/data
                            # paths the app might create sane too.
        import app as qc_app  # noqa: E402  (import after sys.path setup)

        host = self.cfg.get("server", "host", fallback="0.0.0.0")
        port = self.cfg.getint("server", "port", fallback=8001)

        # log_config=None: uvicorn's default logging setup tries to colourize
        # console output by calling sys.stdout.isatty(), which crashes with
        # AttributeError in any console=False build (SpringQCService.exe,
        # SpringQCDesktop.exe) where sys.stdout is None. Disabling it entirely
        # is safe here - our own root-logger handlers (file + GUI tail) already
        # capture uvicorn's loggers via propagation either way.
        config = uvicorn.Config(qc_app.app, host=host, port=port, log_level="info", log_config=None)
        self._uvicorn_server = uvicorn.Server(config)

        if open_browser is None:
            open_browser = self.cfg.getboolean("server", "open_browser", fallback=True)
        if open_browser:
            page = self.cfg.get("server", "browser_page", fallback="/admin")
            threading.Thread(target=self._open_browser_when_ready, args=(host, port, page), daemon=True).start()

        log.info("Spring QC server starting on http://%s:%s", host, port)
        self._uvicorn_server.run()  # blocks until should_exit is set
        log.info("Spring QC server stopped")
        if self._pg:
            self._pg.stop()

    def _open_browser_when_ready(self, host: str, port: int, page: str) -> None:
        import urllib.request

        url = f"http://127.0.0.1:{port}{page}"
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
                webbrowser.open(url)
                return
            except Exception:
                time.sleep(1)
        log.warning("Server did not come up in time to auto-open the browser; open %s manually", url)

    def request_stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True


def main() -> None:
    _setup_logging()
    log.info("Spring QC server launcher starting (frozen=%s, app_dir=%s)", FROZEN, APP_DIR)
    server = SpringQCServer()
    try:
        server.start()
    except Exception:
        log.exception("Spring QC server failed to start")
        raise


if __name__ == "__main__":
    main()
