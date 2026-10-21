# Site / edge deployment

One edge box runs the whole stack; the admin PC and every operator touch
panel are just browsers pointed at it over the local network. Nothing to
install on the admin PC or the HMI panels.

```
Edge box (GPU, static IP, e.g. 192.168.1.50)
  docker compose  ->  db (Postgres, localhost-only)  +  app (:8001, LAN-wide)
      ^                                                        ^
      |                                                        |
  Admin PC: browser -> http://192.168.1.50:8001/admin   Operator HMI panel(s):
                                                          kiosk browser -> .../operator
```

## 1. Edge box — one-time setup

1. Install Docker (Desktop on Windows, Engine on Linux) and, if it has an
   NVIDIA GPU, the NVIDIA Container Toolkit — see the main `README.md`
   "GPU (default) vs CPU" section.
2. Give it a **static IP** on the shop-floor LAN (or a DHCP reservation on the
   switch/router). Write it down - every panel and the admin PC use it.
3. `cp .env.example .env` and set a real `POSTGRES_PASSWORD`.
4. `docker compose up -d --build` from the `spring-qc-app` folder.
5. **Windows only:** run `open-firewall.ps1` in an elevated PowerShell once.
   It allows inbound 8001 (so the LAN can reach the app) and deliberately
   does **not** open 5432 - Windows Firewall default-denies any inbound port
   with no matching allow rule, so Postgres stays unreachable from the floor
   even though the container publishes it on all interfaces. Run
   pgAdmin/psql on the edge box itself (`localhost:5432`) if you need direct
   DB access. (Linux: ufw's default-deny does the same - just don't `ufw
   allow 5432`.)
6. Make sure the stack survives a reboot / power cut:
   - `restart: unless-stopped` is already set on both containers.
   - Windows: put Docker Desktop in `shell:startup` (or enable "Start Docker
     Desktop when you log in" in its settings) so containers come back after
     a power cycle.
   - Linux: `sudo systemctl enable docker` (Engine already restarts
     `unless-stopped` containers on boot once the daemon is up).
   - Put the box on a UPS if the site has power blips - an unclean shutdown
     mid-write is the main risk to the database.

Confirm it's reachable from another machine on the LAN before wiring up the
panels: `http://192.168.1.50:8001/` should load the station picker.

## 2. Admin

Any PC/laptop on the same LAN - just open
`http://192.168.1.50:8001/admin` in a normal browser. No kiosk mode, no
install.

## 3. Operator touch panel(s)

Each machine gets a touch panel (industrial panel PC, or a tablet in a kiosk
mount) running a browser locked to `http://192.168.1.50:8001/operator` in
full-screen kiosk mode, launched automatically on boot.

- **Windows panel:** edit `EDGE_HOST` in `kiosk-operator.bat`, then put a
  shortcut to it in `shell:startup` (Win+R -> `shell:startup`).
- **Linux panel:** edit `EDGE_HOST` in `kiosk-operator.sh`, `chmod +x` it,
  and install `spring-qc-kiosk.service` as a systemd `--user` unit (steps are
  in the comment header of that file) so it launches on login and restarts
  itself if the browser ever crashes.
- Disable screen blanking / screensaver / sleep on the panel - a kiosk that
  goes black defeats the point. Both scripts already disable X11 DPMS on
  Linux; on Windows, turn off sleep in Settings -> Power.
- The operator UI itself needs no further setup - PIN pad and decision
  buttons are already touch-sized.

One edge box can drive several panels: each operator gets their own camera
or test-video assignment, their own ROI, and their own S.No sequence from
the same server, so add one panel per machine and assign it to that
operator from `/admin`.

## Security notes for a floor deployment

- Keep the edge box off any network segment with internet egress, or
  firewall 8001 to just the floor subnet - there's no auth in front of
  `/admin` today, so anyone who can reach port 8001 can reach it.
- Postgres (5432) is published by the container but reaches nowhere unless
  the host firewall allows it - `open-firewall.ps1` intentionally only opens
  8001. Don't add a 5432 allow rule unless you specifically need a remote
  DB client.
- Operator PINs are salted/hashed in the database, but the PIN pad itself is
  not rate-limited - fine for a trusted shop floor, not for a
  publicly-reachable deployment.
- If you ever need to reach this from off-site, use a VPN back into the
  floor LAN rather than port-forwarding 8001 to the internet.
