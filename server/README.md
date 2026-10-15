# Bahi — your Tally on your phone

Three parts:

- **Server** (this folder) runs on Unraid in Docker. It keeps a copy of your Tally data and serves the phone app.
- **Sync agent** (Bahi-TallyPC.zip) runs on the Tally PC every 10 minutes and sends changes to the server.
- **Phone app** is a web app you install from Chrome. It feels like a normal app and works with the last-synced data even when you're offline.

## 1. Server on Unraid

1. Copy this `server` folder to `/mnt/user/appdata/bahi/server`.
   If your appdata share is visible on the network, copy it there. Otherwise put `Bahi-Server.zip` on any share, open the Unraid terminal (top right `>_`) and run:
   ```
   mkdir -p /mnt/user/appdata/bahi && unzip -o /mnt/user/YOURSHARE/Bahi-Server.zip -d /mnt/user/appdata/bahi
   ```
2. Make two secrets. In the Unraid terminal, run `openssl rand -hex 24` twice and keep the two strings. One is the **app password**. Pick something you can type on your phone if you prefer. The other is the **sync token**.
3. Build the image once in the Unraid terminal:
   ```
   docker build -t bahi:local /mnt/user/appdata/bahi/server
   ```
   (Repeat this whenever you get an updated server zip, then Compose Down / Up.)
4. In **Docker → Compose → Add New Stack**, name it `bahi`. Paste the contents of `docker-compose.yml`, put your two secrets in place of `change-this-...`, then click **Compose Up**.
5. Check it from a PC on your home network: open `http://UNRAID-IP:8780`. You should see the login screen.

## 2. Sync agent on the Tally PC

1. Unzip `Bahi-TallyPC.zip` into a permanent folder, e.g. `C:\Bahi`. Don't keep it in Downloads.
2. Tally must still have **F1 → Settings → Connectivity → Client/Server configuration** set to *Both*, ODBC *Yes*, port *9000*, as in the test.
3. Open TallyPrime with your company, then double-click **Setup.bat**. It asks for:
   - **Server address**: `http://UNRAID-IP:8780`. Use the Unraid LAN IP if the Tally PC is in the same building. Otherwise use the Unraid Tailscale IP (100.x.x.x).
   - **Sync token**: the SYNC_TOKEN from the compose file.
   - **From date**: leave blank for the current financial year, or type e.g. `2025-04-01` to include last year.
4. Setup runs a first full sync while you watch, then schedules one every 10 minutes. Syncs run silently and only send data when something changed in Tally.

`Sync-Now.bat` forces a full sync at any time. `TallySync.log` in the same folder shows what happened.

## 3. Reaching it from your phone (Cloudflare Tunnel)

1. In the Cloudflare dashboard, go to your existing tunnel → **Public Hostname → Add**: e.g. `books.yourdomain.com`, service `HTTP`, URL `UNRAID-IP:8780`.
2. Strongly recommended: **Zero Trust → Access → Applications → Add → Self-hosted** for `books.yourdomain.com`, with a policy allowing only your email. Cloudflare then asks for a one-time email code before anyone even sees the login page.
3. On your phone, open `https://books.yourdomain.com` in Chrome, log in with the app password, then use **⋮ → Add to Home screen → Install**.

The sync agent talks to the server directly on port 8780 over your LAN or Tailscale, so it doesn't go through Cloudflare Access.

## Updating to a new version

**Server:** unzip the new `Bahi-Server.zip` over the old one (same command as step 1), then run:
```
docker build -t bahi:local /mnt/user/appdata/bahi/server
```
Then click **Compose Down** and **Compose Up** on the bahi stack. If the database layout changed, it's rebuilt automatically on the next sync, so you don't need to do anything.

**Tally PC:** unzip the new `Bahi-TallyPC.zip` into `C:\Bahi` and let it overwrite the files. Your settings file is kept. Then double-click `Sync-Now.bat` once.

## Installing from the Unraid template (once the GitHub image exists)

1. In the Unraid terminal:
   ```
   wget -O /boot/config/plugins/dockerMan/templates-user/my-bahi.xml https://raw.githubusercontent.com/bdlnaredi/bahi/main/unraid/bahi.xml
   ```
2. Compose Down the old bahi stack (keep `/mnt/user/appdata/bahi/data`).
3. **Docker → Add Container → Template: bahi**. Fill in the app password and sync token (the same ones as before), then click **Apply**.
4. From then on, Unraid's **Check for updates** picks up new versions automatically.

## Good to know

- Figures come from Tally as of the last sync. The line under the company name shows when that was, and whether Tally is currently reachable.
- Closing balances come straight from Tally. Running balances in a ledger are worked backwards from Tally's closing, so they always end on Tally's figure.
- **Dues** shows bill-wise outstanding. It uses Tally's own Bills Receivable/Payable report when available, and otherwise works the bills out from the bill references in your vouchers. Any amount not linked to a bill shows as "On account".
- **GST summary** is a quick check worked out from your vouchers. File returns from Tally or the GST portal.
- PDFs use a standard font, so names written in Hindi or other scripts print as "?".
- If the sync log says some vouchers "did not balance", note the voucher number and report it. That voucher type needs special handling.
- Back up `/mnt/user/appdata/bahi/data` if you like, but it can always be rebuilt with `Sync-Now.bat`.
