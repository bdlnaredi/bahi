# Bahi: your TallyPrime books on your phone

Bahi is a free, self-hosted alternative to apps like Credflow and Livekeeping. A small agent on your Tally PC copies your books to your own server, and you open them on your phone. You can see ledgers, vouchers, bill-wise dues, stock, GST and reports, and share Tally-style PDFs on WhatsApp.

<table>
<tr>
<td><img src="docs/images/home.png" width="230" alt="Home screen"></td>
<td><img src="docs/images/ledger.png" width="230" alt="Party ledger"></td>
<td><img src="docs/images/dues-bills.png" width="230" alt="Bill-wise dues"></td>
<td><img src="docs/images/voucher.png" width="230" alt="Voucher view"></td>
</tr>
</table>

*Screenshots use made-up demo data.*

## What you get

- **Home dashboard:** what you will receive, what you owe, cash, bank, stock value, and monthly sales.
- **Ledgers:** search any ledger and see the full statement with running balance. Call, WhatsApp, or share a PDF.
- **Vouchers:** search by party, voucher number, amount or narration. Open any voucher as an invoice with items, GST, bill references and narration.
- **Dues:** bill-wise receivables and payables with ageing (0-30, 31-60, 61-90 and 90+ days), overdue amounts, and WhatsApp payment reminders that list the overdue bills.
- **Stock:** quantity, rate and value of every item, plus item movements.
- **Reports:** Day Book, Profit & Loss, GST summary (output tax, input credit and net payable by month), and a group summary.
- **PDFs like TallyPrime prints:** Tax Invoice, Receipt/Payment/Journal voucher, and Ledger Account.
- **Works offline:** your phone keeps the last data you opened.
- **Private:** your data lives on your own server. The app needs a password, and you can put Cloudflare Access in front of it.

## How it works

<img src="docs/images/how-it-works.svg" alt="Tally PC sync agent sends data to the Bahi container on Unraid; the phone opens it through Cloudflare Tunnel" width="100%">

1. TallyPrime's built-in data server (port 9000) lets programs on the same PC read your books.
2. The **sync agent** (PowerShell, no install needed) runs every 10 minutes. When something has changed in Tally, it reads masters, vouchers and outstanding bills and sends them to your server.
3. The **Bahi server** (one Docker container) stores the data and serves the phone app.
4. Your **phone** opens the app in Chrome and installs it to the home screen like a normal app.

## Get started

- **[Installation guide](docs/INSTALL.md):** set up Tally, Unraid, the Tally PC and your phone, step by step.
- **[User guide](docs/USING.md):** what every screen does.
- **[Troubleshooting](docs/INSTALL.md#troubleshooting)**

## Repository layout

| Folder | What's inside |
|---|---|
| `server/` | The Docker app. Python standard library only, no extra packages. |
| `agent/` | Sync agent for the Windows PC that runs TallyPrime. |
| `unraid/bahi.xml` | Unraid Docker template. |
| `tests/mock_tally.py` | A simulated Tally server used for testing without real books. |
| `docs/` | Guides and screenshots. |

The Docker image is built automatically on every change and published as `ghcr.io/bdlnaredi/bahi:latest`.

## License

Copyright (C) 2026 bdlnaredi

Bahi is free software: you can redistribute it and/or modify it under the terms of the
[GNU General Public License version 3](LICENSE) or any later version. If you share a changed
version, you must share its source code under the same license. Bahi comes with no warranty.

Bahi is not affiliated with or endorsed by Tally Solutions. TallyPrime is a trademark of its owner.
