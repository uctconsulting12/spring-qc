# Spring QC — Install & Use Guide

A start-to-finish guide: install the server once, hand out browser
shortcuts to everyone else, configure it, and run the line day to day.

**Who this is for:** whoever sets up the plant-floor PC and the person who
will use the Admin dashboard day to day. No Docker, no Python, no command
line beyond the copy-paste steps below.

---

## 0. The architecture in one picture

```
                     Plant-floor LAN (one switch, no internet needed)
   ┌──────────────────────────────────────────────────────────────────┐
   │                                                                    │
   │   THE SERVER (one PC, has the GPU)                                 │
   │   ──────────────────────────────                                  │
   │   Runs as a Windows Service, in the background, always on:         │
   │   camera → AI model → database → web pages on port 8001            │
   │                                                                    │
   │        ▲                    ▲                    ▲                │
   │        │                    │                    │                │
   │   Admin PC             Operator PC           Monitor / TV          │
   │   (browser)            (browser)             (browser)             │
   │   Desktop icon         Desktop icon          Desktop icon           │
   │                                                                    │
   └──────────────────────────────────────────────────────────────────┘
```

One PC does the work (the "server" — an industrial PC with an NVIDIA GPU).
Everyone else — the admin, the operators, anyone watching a monitor — just
opens a normal web browser to a shortcut on their own PC. Nothing installs
on those other PCs except a Desktop icon.

---

## Part 1 — Install the server (do this once)

This goes on the **one PC that has the GPU** and will run continuously.

### 1.1 Get the files onto that PC

Copy the whole `SpringQCServer` folder onto the server PC, e.g. to
`C:\SpringQC\Server\`. This folder contains everything it needs — the app,
the AI model, and its own database engine. Nothing else needs to be
installed first (no Python, no Postgres, no Docker).

> If you built the polished installer (`SpringQC-Server-Setup.exe` via
> `server\installer\build_installer.bat`), just run that instead and skip
> to §1.4 — it does steps 1.1–1.3 for you and installs to `C:\SpringQC\Server`
> automatically.

### 1.2 Try it once, in the foreground

Before installing it as a background service, run it once by hand to make
sure everything's happy on this PC:

1. Open `C:\SpringQC\Server\`
2. Double-click **`SpringQCServer.exe`**
3. A black console window opens and logs a few lines, ending with something
   like:
   ```
   GPU acceleration: ENABLED - <your GPU name> (... GB VRAM, CUDA ...)
   Spring QC server starting on http://0.0.0.0:8001
   ```
   Your browser opens automatically to the Admin page.
4. **If it says GPU acceleration was NOT available**, stop and check the
   NVIDIA driver is installed on this PC before continuing — everything
   still works on CPU, but a live camera feed will lag badly.
5. Close the console window (or press `Ctrl+C` in it) once you've confirmed
   this worked. This was just a test run.

### 1.3 Install it as a background service (do this for real use)

This is what makes it start automatically and keep running with nobody
logged in — the actual "always on, always inferencing" setup.

1. Right-click **Start** → **Terminal (Admin)** (or "Command Prompt (Admin)")
2. Run:
   ```
   cd C:\SpringQC\Server
   SpringQCService.exe install
   SpringQCService.exe start
   ```
3. Confirm it's running: open **Services** (`Win+R` → `services.msc`), find
   **"Spring QC Inference Server"** — it should say **Running**, startup
   type **Automatic**.

From now on this PC serves Spring QC automatically, from the moment
Windows boots, whether or not anyone is logged in.

**To stop/remove it later**, from an admin prompt in the same folder:
```
SpringQCService.exe stop
SpringQCService.exe remove
```

### 1.4 Write down this PC's IP address

You'll need it for every other PC. Run `ipconfig` in a Command Prompt on
the server PC and note the **IPv4 Address** (e.g. `192.168.1.50`). Better
still, give this PC a **static IP** or a DHCP reservation on your router so
it never changes.

### 1.5 Confirm it works from another PC

From any other PC on the same network, open a browser and go to:
```
http://192.168.1.50:8001/admin
```
(using the IP you noted). You should see the Admin dashboard. If not, see
[Troubleshooting](#troubleshooting) below.

---

## Part 2 — Set up every other PC (admin, operator, monitor)

No install here — just a Desktop icon that opens a browser to the right
page.

1. Copy the `client-shortcuts` folder to that PC (a USB stick or a shared
   network folder both work).
2. Double-click **`install-shortcuts.bat`**.
3. When it asks for the server's IP address, type the one from §1.4
   (e.g. `192.168.1.50`) and press Enter.
4. Four new Desktop icons appear:
   - **Spring QC - Admin**
   - **Spring QC - Operator**
   - **Spring QC - Monitor**
   - **Spring QC - Reports**

Double-click the one this PC needs. It opens in whatever browser is
already the default on that PC (Chrome, Edge, whatever) — nothing new to
install.

> **Only want one icon on this PC** (e.g. an operator station that should
> only ever show the Operator screen)? Instead of the `.bat` file, right-click
> **`Create-SpringQCShortcuts.ps1`** → **Run with PowerShell**, or run from
> a PowerShell prompt:
> ```powershell
> .\Create-SpringQCShortcuts.ps1 -ServerAddress 192.168.1.50 -Pages Operator
> ```

Repeat this on every PC that needs to reach Spring QC: the admin's desk,
each operator station, and any monitor/TV PC.

---

## Part 3 — First-time setup (do this from the Admin PC)

Open the **Spring QC - Admin** shortcut. This is the control center: add
operators, assign cameras, and go live.

### 3.1 Add your operators

1. Click **Operators** (top of the page).
2. Click **Add Operator**.
3. Enter their name, machine number, and set a 4-digit PIN they'll use to
   sign in.
4. Repeat for each operator.

### 3.2 Assign a camera (or a test video) to an operator

1. Click **Assign Camera / Video**.
2. Pick the operator.
3. Choose either:
   - **RTSP Camera** — paste the camera's RTSP URL (get this from your
     camera's setup page — it usually looks like
     `rtsp://user:pass@192.168.1.60:554/stream1`), or
   - **Test Video** — upload a recorded video file to try things out
     before a camera is wired up.
4. Click **Save**. A preview frame from the camera/video appears.

### 3.3 Set the ROI (region of interest)

The ROI is the zone on the camera image where a spring counts as
"in view." On the preview frame:

1. Click points around the area where springs pass through, to draw a
   polygon (at least 3 points, e.g. the 4 corners of the conveyor lane).
2. Click **Save ROI**.

You can redraw this any time — click **Edit ROI** next to that operator's
assignment. If a camera moves, this is the first thing to check.

### 3.4 Go live

Toggle **Live** on for that operator's assignment. The system starts
watching the camera and detecting springs immediately.

### 3.5 (Optional) Fine-tune detection settings

Click **Settings** if the default detection sensitivity needs adjusting for
your line — confidence threshold, tracker choice, how many frames a spring
must be seen for before it counts, etc. Each setting has an **(i)** info
icon explaining what it does in plain terms. Defaults work well for most
setups — only change these if you're seeing missed springs or false
detections.

---

## Part 4 — Daily use: the Operator

The operator opens the **Spring QC - Operator** shortcut (or it's already
open, left running from the previous shift).

1. **Sign in**: tap your name, then enter your 4-digit PIN on the number
   pad.
2. Watch the screen. When a spring passes through the camera's ROI and
   leaves it, the screen shows the captured photos of that spring and
   waits for a decision.
3. Tap one of:
   - **Not Defective**
   - **Defective**
   - **Skip** (if the photos are unclear or you're unsure)
4. The screen returns to waiting for the next spring. Repeat all shift.

That's the entire operator workflow — no keyboard needed, everything is
big touch targets.

---

## Part 5 — Daily use: Admin / Supervisor

### Watching live

Open **Spring QC - Monitor**, pick an operator from the dropdown to watch
their camera feed and see spring events land in real time. This is
view-only — decisions are made by the operator, not from here.

### Reports

Open **Spring QC - Reports** for:
- Daily/weekly inspection counts and defect rate, with charts
- Per-operator breakdowns
- A searchable table of every inspection, with the captured photos
- **Export Excel** — pick a date range/operator/result filter and download
  a spreadsheet with the inspection data and photos embedded, for sharing
  or record-keeping

### Changing a camera or operator later

Back in **Admin**, you can change any operator's camera/video assignment,
redraw their ROI, or add/remove operators at any time — go live status can
be toggled off first if you need to change the source, but **ROI edits
apply to a live camera immediately**, no need to stop it first.

---

## Maintenance

### Restarting the server

From an admin Command Prompt on the server PC:
```
net stop "SpringQCServer"
net start "SpringQCServer"
```
(or use the **Services** app — right-click **"Spring QC Inference Server"**
→ Restart). Any operator screens left open will show "reconnecting" for a
few seconds and pick back up automatically.

### Checking logs

If something's misbehaving, the server's logs are at:
```
C:\ProgramData\SpringQC\logs\server.log
```
This is a plain text file — open it in Notepad. It logs GPU status, startup,
and errors.

### The database

Your data (operators, PINs, every inspection decision, captured photos)
lives under `C:\ProgramData\SpringQC\`. This survives restarts, updates,
and reboots — it's not inside the app folder. **Back this folder up
periodically** the same way you'd back up any other important folder on
that PC.

### Updating the app

Get the new `SpringQCServer` build, stop the service
(`SpringQCService.exe stop`), replace the old `C:\SpringQC\Server` folder's
contents with the new build (leave `springqc.ini` if you've customized it),
then start it again (`SpringQCService.exe start`). Your data in
`C:\ProgramData\SpringQC\` is untouched by this.

---

## Troubleshooting

**Client PC's browser shortcut shows "can't reach this page"**
- Confirm the server PC is powered on and the service is **Running** (open
  `services.msc` there).
- Confirm both PCs are on the same network/switch.
- Confirm the IP address used when creating the shortcut is still correct
  (re-run `install-shortcuts.bat` with the right IP if the server's address
  ever changes — better to give it a static IP so this never happens).
- Try `http://<server-ip>:8001/admin` directly in a browser to isolate
  whether it's a shortcut problem or a network problem.

**Server log says GPU acceleration is NOT available**
- Check the NVIDIA driver is installed and up to date on the server PC
  (Device Manager → Display adapters should show the GPU with no warning
  icon).
- The app still runs on CPU, but a live camera will fall behind — this
  should be fixed before going live on an actual line.

**Operator can't sign in / wrong PIN**
- An admin can reset this: **Admin → Operators → Edit** that operator, set
  a new PIN.

**Camera preview / ROI step shows no image**
- Double-check the RTSP URL (test it in VLC: *Media → Open Network Stream*
  with the same URL, to confirm the camera itself is reachable and the
  credentials are right) before troubleshooting inside Spring QC.

**Springs are being missed, or phantom springs appear with nothing there**
- Adjust **Settings → IN confirmation window** (higher = fewer phantom
  springs, but slower to register a real one) and **confidence threshold**.
  See the **(i)** tooltips next to each setting in the Admin Settings panel.

---

## Quick reference

| What | Where |
|---|---|
| Admin dashboard | `http://<server-ip>:8001/admin` |
| Operator station | `http://<server-ip>:8001/operator` |
| Live monitor | `http://<server-ip>:8001/monitor` |
| Reports | `http://<server-ip>:8001/reports` |
| Server install folder | `C:\SpringQC\Server\` |
| Server data (DB, logs, photos) | `C:\ProgramData\SpringQC\` |
| Server logs | `C:\ProgramData\SpringQC\logs\server.log` |
| Start/stop the service | `SpringQCService.exe start` / `stop` (admin prompt, from the install folder) |
| Add client shortcuts | `client-shortcuts\install-shortcuts.bat` |
