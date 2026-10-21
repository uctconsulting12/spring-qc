"""
Spring QC Server - Windows Service wrapper.

Wraps springqc_launcher.SpringQCServer in a real Windows Service (via
pywin32) so the inference server survives a reboot and starts before any
operator logs in - matching the `restart: unless-stopped` behaviour the
Docker deployment gets for free. This is the recommended way to run the
edge-box build in production; the plain .exe from springqc_launcher.py is
for interactive / first-run use.

Install (elevated cmd/PowerShell, from the installed location):
    SpringQCService.exe install
    SpringQCService.exe start

    net start SpringQCServer      (equivalent, once installed)

Uninstall:
    SpringQCService.exe stop
    SpringQCService.exe remove

The Inno Setup installer (installer/SpringQC-Server.iss) runs these for you.
"""
from __future__ import annotations

import logging
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from springqc_launcher import SpringQCServer, _setup_logging

log = logging.getLogger("springqc.service")


class SpringQCService(win32serviceutil.ServiceFramework):
    _svc_name_ = "SpringQCServer"
    _svc_display_name_ = "Spring QC Inference Server"
    _svc_description_ = (
        "Runs the Spring QC detection/tracking API and web UI (Admin / Operator / "
        "Monitor / Reports) with GPU-accelerated inference. Starts automatically on boot."
    )

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = SpringQCServer()
        self._thread: threading.Thread | None = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        log.info("Service stop requested")
        self.server.request_stop()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        _setup_logging()
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        # uvicorn.Server.run() blocks, so it needs its own thread - SvcDoRun
        # itself has to return control to the service control manager only
        # on shutdown, via waiting on stop_event.
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        self._thread.join(timeout=30)

    def _run_server(self):
        try:
            # A service has no console and no one to click a browser open for.
            self.server.start(open_browser=False)
        except Exception:
            log.exception("Spring QC service crashed")
            servicemanager.LogErrorMsg("Spring QC Server crashed - see ProgramData\\SpringQC\\logs\\server.log")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(SpringQCService)
