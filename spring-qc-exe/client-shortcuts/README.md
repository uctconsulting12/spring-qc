# Client shortcuts

The "menu or shortcuts" piece: Desktop / Start Menu icons on the admin PC and
any operator/monitor viewing PC, so nobody has to type an IP address. No
install, no admin rights, nothing to build — these are just `.url` files
(the same "Internet Shortcut" format Windows itself uses), which open in
whatever the default browser is.

This is the actual client-side architecture: **a normal web browser**,
pointed at the one server running `SpringQCService.exe` (see `../server/`),
reached over the plant LAN. Nothing runs on the client PC except the
browser.

## Use

On each client PC (the admin PC, an operator-facing PC, a monitor screen):

1. Copy this folder over (or just the two files below).
2. Double-click **`install-shortcuts.bat`**.
3. Enter the server's IP address when asked (e.g. `192.168.1.50` — the
   machine running `SpringQCService.exe`).
4. Four shortcuts appear on the Desktop: **Admin**, **Operator**,
   **Monitor**, **Reports**. Double-click one to open that screen.

For a PC that should only ever show one screen (an operator panel that
should never accidentally end up on the Admin page), run the PowerShell
script directly instead, with just the page you want:

```powershell
.\Create-SpringQCShortcuts.ps1 -ServerAddress 192.168.1.50 -Pages Operator
```

Add `-AlsoStartMenu` to also create a "Spring QC" Start Menu folder.

## Linux (or any other OS with a browser)

The HMI is just a web page - any OS on the same LAN can reach it with
nothing installed beyond a browser, which every desktop already has. For a
Linux client, use `create-springqc-shortcuts.sh` instead of the `.bat`:

```bash
chmod +x create-springqc-shortcuts.sh
./create-springqc-shortcuts.sh 192.168.1.50
# or just:
./create-springqc-shortcuts.sh        # prompts for the IP
```

Creates the same four shortcuts (Admin / Operator / Monitor / Reports), as
`.desktop` launcher files on the Desktop and in the application menu - the
Linux equivalent of the Windows `.url` files. Pass a page name to create
just one, e.g. `./create-springqc-shortcuts.sh 192.168.1.50 8001 operator`
for a panel that should only ever show the Operator screen.

On a Mac, or any client without one of these two scripts, there's nothing
to install at all - just bookmark `http://<server-ip>:8001/operator` (or
`/admin`, `/monitor`, `/reports`) in the browser.

## If you need a locked-down kiosk instead

A plain browser shortcut is enough for most PCs — someone can still close
the tab or navigate away, which is fine for an admin PC or a monitor
screen nobody is meant to touch all day. If a specific operator touch
panel needs to be genuinely locked to one screen (no address bar, can't
navigate away, launches automatically on boot), that's what
`../hmi/SpringQCHMI.exe` is for — build it separately per `../hmi/README`
notes in the top-level `spring-qc-exe/README.md`. It's optional, not the
default.
