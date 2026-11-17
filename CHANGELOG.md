# Changelog

Everything that changed in Bahi, newest first. The version is the server version shown in the app under Settings. "Tally PC" is the sync on the PC that runs TallyPrime (Bahi Sync), which updates itself from the server.

## 3.25.0 (17 November 2026)

- **TDS and TCS** (Reports): from Tally's TDS/TCS ledgers. It shows what you deducted or collected each month, what you paid to the government, the due date (7th of the next month, 30 April for March) and whether it was late. Totals are listed by section ledger and by party. TDS your customers deducted from you is listed apart, to check against Form 26AS.
- **Cheque register** (Reports): cheques received and issued.
  - From Tally: cheque number, date and bank on receipts and payments, shown as cleared once the bank date is set in Tally.
  - Written down in Bahi: post-dated cheques you're holding, which you can mark deposited, cleared or bounced.
  - Home shows the cheques due within a week.
- **Stock count** (Reports): count the shelves on your phone, by typing quantities or scanning barcodes, and compare with Tally's stock item by item.
  - Shows what's short or extra, with its value. Several people can count at once.
  - Share the differences on WhatsApp. Tally's stock isn't changed.
- **Fixed:** in 3.23 and 3.24, setting the sales target, marking a statement as sent and removing a GSTR-2B file didn't save. They do now.
- The Tally PC reads all vouchers again once, to pick up cheque details and post-dated marks.

## 3.24.0 (17 November 2026)

- **GSTR-2B matching** (Reports): upload the GSTR-2B JSON (or zip) from the GST portal. Bahi matches each supplier bill with your purchase bills in Tally by GSTIN and bill number, and sorts them into:
  - **Matched:** same bill, same tax.
  - **Tax differs:** the bill is in both, but the tax doesn't agree.
  - **In 2B, not in Tally:** enter the bill in Tally, or check its number.
  - **In Tally, not in 2B:** the supplier hasn't filed it, so that credit is at risk.
- **E-invoice and e-way bills** (Reports): sales for the month that seem to need an e-invoice (sales to registered buyers, once your company issues e-invoices) or an e-way bill (goods over ₹50,000) but have none in Tally.
- **Year-end checklist** (Reports): vouchers that don't balance, stock below zero, cash below zero, suspense balances, bank accounts not reconciled, bills unpaid for over a year, advances, GST ledger balances, items without HSN or GST, and customers without a phone number. Each has the list and a link.
- **Staff activity** (Reports, owner only): who made which entry, reminder, quotation or change in the app, and when, with a filter by person. Logins are listed too.
- Backups now include GSTR-2B files, statement marks, sales targets and the activity log.

## 3.23.0 (17 November 2026)

- **Cash flow forecast** (Reports): cash and bank over the next 30 days, as a chart and day by day.
  - It starts from your Tally balances, adds customers' bills on their due dates, and takes away suppliers' bills and your usual daily spending.
  - It shows the lowest point and its date. Overdue bills are listed apart, as they may or may not come in.
- **Customers who stopped buying** (Reports): regular buyers who haven't bought for more than twice their usual gap. Each has a WhatsApp "we miss you" message and a call button.
- **Month-end statements** (Reports): every customer who owes you, with a Send button that opens WhatsApp with their balance and a link to their statement.
  - Sends are marked for the month, so you or your staff can carry on from another phone.
  - Home reminds you in the first week of the month.
- **Sales target:** the owner sets a monthly target from Home. Home shows the progress bar, whether you're on track, and the sales needed each day to reach it.
- **Price list** (Reports): your items with rates (the last rate each was sold at in Tally), by stock group, with or without GST, as a PDF to share or print.
- **Payment notifications** (Android app, Settings, Android app): turn on to get "₹… received from …" on your phone when a receipt comes in from Tally. Tap it to open the receipt.
- **Say thank you:** a receipt voucher now has a WhatsApp thank-you button.

## 3.22.0 (17 November 2026)

- **GSTR-3B reworked:**
  - **Clear signs:** a minus figure used to show as plus. The screen now says *Cash to pay* and *Credit carried forward* instead of one "left to pay" figure.
  - **Reverse charge (URD purchases):** shown in its own place. Tax payable is in 3.1(d) and the matching credit in 4(A)(3); the rest of the credit is in 4(A)(5). Reverse-charge tax is paid in cash, never from credit.
  - Bahi reads reverse charge from Tally's own marks: the voucher's *reverse charge applicable* or *unregistered dealer (RCM)* flag, or a GST adjustment journal whose nature names reverse charge or an unregistered dealer. A tax line credited on a purchase is also counted as reverse charge.
  - **Set-off as on the GST portal:** IGST credit is used first, on IGST, then on CGST and SGST. Then CGST credit is used on CGST and then IGST, and SGST credit on SGST and then IGST. CGST and SGST credit never cross. Each head shows what each credit paid and the cash left to pay.
  - **Credit brought forward:** a debit balance on your GST ledgers in Tally at the start of the month counts as earlier credit and is used in the set-off.
  - **Your GST ledgers in Tally:** a new card shows each head's balance at the start and end of the month, as it is in Tally, marked Dr or Cr.
  - **One ledger for both sides:** tax is now sorted by the voucher it's on (sale, purchase, journal), not by the ledger's name. So a single CGST ledger used for both sales and purchases is counted correctly.
- **Re-read once:** the Tally PC reads all vouchers again once, to pick up the reverse-charge marks.

## 3.21.1 (17 November 2026)

- **GSTR-3B on phones:** the table was wider than the screen, so the CGST and SGST columns were hidden off to the right and the figures looked out of place. Each part (3.1(a), 3.1(c), 4 and what's left to pay) is now its own card with IGST, CGST, SGST and the total each on its own line.

## 3.21.0 (17 November 2026)

- **App lock** (Android app, Settings, Android app): Bahi asks for your fingerprint, face or phone PIN when it opens, and when you come back to it after more than a minute.
- **Home-screen widget** (Android app): today's sales and bills, cash and bank, and money to receive for the company you last opened, with the time of the data. It refreshes every 30 minutes and whenever you open Home; tap it to open Bahi. To add it, long-press the home screen, then Widgets, then Bahi.
- Backups now also include quotations, reminder marks and credit warning settings.
- The user guide has sections for all the new features.

## 3.20.0 (17 November 2026)

- **Reorder list** (Reports, or Stock): items to buy now, grouped by the supplier you last bought each from.
  - An item is listed when it's at or below the reorder level set in Tally (or the minimum set in Bahi), or will run out within 15 days at its recent selling rate.
  - The suggested quantity covers about a month and keeps to Tally's minimum order.
  - *Send to supplier* opens WhatsApp with the list ready to send; *Copy list* copies it.
- **Item profit** (Reports): profit and margin on each item and each customer for any period. Selling value less the cost of what was sold, at the item's average purchase rate in Tally.
- **Quotations** (Reports): make a quotation for a Tally customer or anyone else, with items, GST and validity.
  - Share or print it as a PDF laid out like your Tally invoice, titled Quotation.
  - Mark it lost, or tap *Make sales order*: the order form opens filled in. Nothing goes into Tally until that order is saved.

## 3.19.0 (17 November 2026)

- **GSTR-1 and GSTR-3B** (Reports): the month's returns in summary, put together from your Tally vouchers, to check before filing.
  - **GSTR-1:** B2B invoices (with each customer's GSTIN), B2C Large, B2C Small by rate, credit and debit notes, nil-rated sales, and the HSN summary.
  - **GSTR-3B:** outward taxable supplies and tax, input tax credit, and what's left to pay after the credit.
  - The tax is what's posted on Tally's GST ledgers, and each line's rate is the one Tally gave it. Bahi doesn't file anything: file from Tally's own GSTR reports or with your CA.
- **Compare periods** (Reports): this month, quarter or financial year against the one before and the same one a year ago.
  - Figures: sales, purchases, expenses, other income, money received and paid out, number of bills, average bill and customers billed, with the change in %.
  - Also the customers and items that moved the most.

## 3.18.0 (17 November 2026)

- **Credit warning:** when you make a sales invoice or order, choosing a customer who is over the credit limit set on their ledger in Tally, or who has bills overdue more than 30 days, shows an orange warning with the oldest bills. It's only a warning: the entry can still be saved. Settings, Credit warning turns it off or changes the days.
- **Due dates:** Dues, *Due dates* shows bills by the day they fall due (bill date plus the credit period in Tally): a strip of the next 14 days with the amount on each, everything due in the next month, and what's already overdue. For both money to receive and money to pay.
- **Reminders:** Dues, *Reminders* lists every customer with overdue bills, newly overdue ones first. *Send reminder* opens WhatsApp with the overdue bills, their customer link and UPI payment, and marks them reminded for 7 days (staff see it too). Home shows "N customers to remind today".
- The Telegram morning summary now says what falls due today and how many customers to remind.
- Bahi now reads the credit limit and credit period on ledgers, and the reorder level and minimum order on stock items, from Tally.

## 3.17.2 (15 November 2026)

- **Bill references shown once.** TallyPrime sends a voucher's ledger lines twice (as *all ledger entries* and *ledger entries*), each with the same bill references, and Bahi kept both. Now it reads them from one list only. The Tally PC sends every voucher again once by itself so the stored copies are corrected (the first sync after updating takes a little longer). Pending bills worked out from vouchers are corrected by the same re-read.

## 3.17.1 (15 November 2026)

- **Customer, item and ledger lists work in the Android app again.**
  - When making an invoice or any other entry, tapping Customer, Item, Charge or Ledger opens a list, and typing narrows it (any part of the name, e.g. "gup" finds Gupta Hardware). Tap a name to choose it.
  - Before, these used the browser's own suggestion list, which often shows nothing inside the Android app.

## 3.17.0 (15 November 2026)

- **Copies of TallyPrime's own backups.**
  - Set TallyPrime 7.0's Schedule Backup to save into a folder (Alt+Y, Backup & Restore, Schedule Backup), and pick the same folder in Bahi Sync, Settings, *Tally backup folder*.
  - Bahi Sync then copies each new backup file (like `TSDBK1800_100000.001`) to the Bahi server, exactly as Tally made it. When Google Drive or OneDrive is connected, it goes there too.
  - Download a file, or all of them as a .zip, from Settings, Backups, *Tally's own backups*, and restore it in Tally with Data, Restore.
  - Bahi Sync only reads that folder: it never writes, renames or deletes anything there, and never touches Tally's company data. A file Tally is still writing waits for the next round.
  - Files go up in 16 MB pieces, so big backups also work through Cloudflare. Files Tally has since removed are kept on the server 30 more days.
- Tally PC 3.20.

## 3.16.0 (15 November 2026)

- **Log out from any screen:** a round button with your initial sits at the top right, next to refresh. It opens a menu with who is logged in (owner or staff), Settings, What's new, light or dark look, and **Log out**.

## 3.15.1 (15 November 2026)

- **Tally PC 3.19:**
  - when the Bahi server doesn't answer (it's restarting after an update, or the network drops for a moment), the sync waits and tries again after 5 and then 19 seconds instead of failing straight away;
  - the log gives the real reason ("couldn't reach the Bahi server: Unable to connect ...", "server says: ...") instead of "Exception calling DownloadString".

## 3.15.0 (15 November 2026)

- **"Data as of" date and time everywhere.**
  - The app shows *Data as of 15 Nov 2026, 12:02 pm* in a box under the company name on every screen, for you and your staff. A second line says whether Tally is connected or a sync is running.
  - When the figures are more than 3 hours old, the box turns orange and says how old they are.
  - Customer links show *Figures as on 15 Nov 2026, 12:02 pm* at the top, so customers know which moment their balance is from.
- The time is when Bahi last checked the company against Tally, not just the last time something changed, so a quiet afternoon with no new entries still shows the current time. Tally PC 3.18 reports this after every sync.

## 3.14.0 (15 November 2026)

- **Settings is a short menu now**, grouped like a phone's settings: *Tally and this phone*, *Customers and money*, *People and security* and *Your data*. Each row shows how it's set (Every 10 min, Off, 3 people, Last backup 6 hr ago) and opens on its own screen, instead of one very long page with everything open.

## 3.13.0 (14 November 2026)

- **The app keeps working when the server is down.** If Unraid is off, the internet at the shop is down, or Cloudflare can't reach the server, the app opens straight away with the copy saved on the phone. An orange line says it's showing the saved copy. Before, it could show Cloudflare's error page or keep loading for minutes.
  - When the server is only slow, the saved copy shows after a few seconds, and fresh figures replace it as soon as the server answers.
  - New entries, PDFs and sharing still need the server.
- **What's new:** Reports, What's new lists the changes in every version, newest first. After an update, Home shows a "Bahi has been updated" card that opens it.

## 3.12.1 (14 November 2026)

- **The Android app keeps itself up to date:**
  - it checks for a new version every time it is opened (at most every 15 minutes), not twice a day;
  - when one is ready, it asks you to update every time you open the app, and an orange **New Bahi app ready** bar with an **Update** button stays at the top until you do;
  - it also checks twice a day in the background and sends a notification ("Update the Bahi app"); tap it to update. Android 13 and later ask once to allow notifications.

## 3.12.0 (14 November 2026)

- **Ledgers open on the month of their last entry** (choose *Month of last entry* again from the period list at any time), so a party you last billed in August opens on August instead of an empty month.
- **Print** on ledgers and vouchers. In the Android app it uses the phone's own printing (any printer the phone knows, or Save as PDF); on a computer the print window opens straight away. The Android app needs updating for this (Reports, Update app).
- The figures you will receive are on a **green** card now (what you owe stays red).
- The period picker has a calendar icon and the word *Showing* in front, so it reads as "Showing: This month".

## 3.11.0 (14 November 2026)

- **A simpler, calmer look:**
  - a soft grey background with white cards, and bold colour only on the figures that matter;
  - Home has one **New entry** button that opens a sheet of entry types, instead of a row of nine buttons;
  - the period is one dropdown (This month, This year ...) instead of six buttons.
- **Ledgers:**
  - a bold balance card says in plain words what the balance means: "You will receive", "You owe", "Advance from them", or "Balance" and "Overdrawn" for banks;
  - **Statement** and **Pending bills** are now separate tabs instead of one long page;
  - Share, WhatsApp and Call stay on the screen; PDF, Excel, customer link and UPI request are under **More**.
- **Bank and cash accounts swap the colours:** money in (Dr) is green and money out or an overdraft (Cr) is red, in the ledger, lists, Home and vouchers. A party's ledger keeps Dr red and Cr green.
- On a phone, menus and sheets rise from the bottom of the screen.

## 3.10.2 (14 November 2026)

- While the Tally PC is syncing, the app says so at the top: **Syncing from Tally now** (with the company, when you have several), with a blinking blue dot and when it started. When the sync finishes, the app shows the new figures by itself.

## 3.10.1 (12 November 2026)

- **Tally PC 3.17:** companies with many vouchers no longer get stuck on "Tally didn't send its list of vouchers". Tally now has up to 10 minutes to answer (it was 100 seconds). If the whole list still doesn't come, it is asked for one month at a time, and the log gives Tally's real reason.
- Bahi is listed in Unraid's **Community Apps**: search for *bahi* in the Apps tab.

## 3.10.0 (9 November 2026)

- **New stock items from the app:** Stock, **+ New item**, with name, stock group, unit, HSN, GST rate, alias and barcode. It goes into Tally at the next sync as a new item only; Tally refuses a name it already has, so existing items are never changed. Staff need the new *Add stock items* permission.
- **Barcodes:** scan a barcode to give it to a stock item, then scan items straight into sales, purchases and orders. Each scan beeps, and the scanner waits for **Scan next** or **Done**. An unknown barcode offers *Make a new stock item*.
- Tally PC 3.16: the safety check now allows exactly two kinds of writes into Tally: new vouchers and new stock items.

## 3.9.0 (8 November 2026)

- **Sync to two Bahi servers at once** (Bahi Sync, Settings, *Also sync to*), for example Unraid and a cloud server while you compare them. Phone entries from either one go into Tally only once.
- **Backups in Google Drive or OneDrive** on Unraid too: Bahi Sync, Tools, *Back up to Google Drive* (or OneDrive). Every night's backup is copied there, and the last 30 are kept.

## 3.8.0 (1 November 2026)

- **UPI payment requests:** set your UPI ID in Settings. Ledgers and dues get a *Request payment* button, invoices print a UPI QR code, and customer links show a **Pay with UPI** button.
- **Android app:** update the app from inside the app. Sharing and opening PDFs no longer fails with "java.lang.Throwable".
- **Ledgers and sales follow the period:** this year by month, this quarter by week, this or last month by day.

## 3.7.0 (1 November 2026)

- **Customer links:** each party gets a private read-only page with their balance, pending bills, statement PDF and every invoice. The link is added whenever you share a ledger or voucher on WhatsApp or Telegram, and you can turn any link off.

## 3.6.x (31 October to 1 November 2026)

- **BahiSync-Setup.exe:** installs Bahi Sync in Program Files with a Start menu entry, starts with Windows, and moves an older copy's settings over by itself.
- **Several companies:** tick every company to sync under Companies in Bahi Sync (each with its own start date if you like), then switch between them in the app.
- **Invoice PDFs:**
  - the full invoice number, never cut short;
  - a second page for the e-way bill (on a purchase, *From* is the supplier and *To* is your company);
  - stock lines no longer show twice;
  - a purchase shows the supplier, not your own company;
  - your company's GSTIN, address, bank branch and IFSC, and registrations such as UDYAM or FSSAI, read from where TallyPrime keeps them.
- **GST summary** shows the rate and tax Tally applied to each HSN and stock line, exactly as in Tally, including bills with several GST slabs.

## 3.5.0 (26 October 2026)

- **Telegram ledger lookups:** send the bot a party's name, spelt any way, and get their balance, statement and PDF.
- **Bahi Sync for Windows:** a tray app on the Tally PC with status, log, **Sync now** and settings.
- Tally PC 3.5 to 3.9: a stuck sync no longer blocks the next one; months are counted only on real vouchers; files update only between syncs; a voucher Tally lists but never sends no longer holds up syncing.

## 3.4.x (24 to 26 October 2026)

- **Sales invoices and purchases from the phone**, with items, GST and other charges (labour, loading, packing, cartage). Type the taxable amount and the rate is worked out.
- **Safer syncing:** a month is never replaced with fewer vouchers than Tally lists; the server decides per month and per voucher what to resend.

## 3.3.0 (24 October 2026)

- Balances shown exactly as Tally has them. Voucher type on every entry, with a choice when you have several. Journal and contra entries from the phone.

## 3.2.0 (24 October 2026)

- **Android app** with a full **offline copy**: every ledger, stock item, dues, reports and the last year's vouchers stay on the phone. Cloudflare Access login works inside the app.

## 3.1.0 (18 October 2026)

- Ledger balances are checked against Tally at every month-end and fetched again where they differ.

## 3.0.x (16 to 17 October 2026)

- **The Tally PC updates itself** whenever the server is updated.
- **Bank reconciliation** from an Excel or CSV bank statement.
- **Stock by godown.**
- **Never deletes or changes anything in Tally:** every request is checked on the Tally PC before it reaches Tally.
- Restore backups from the app. Settings and Reports open before the first sync.
- The GSTR-2B check was removed.

## 2.9 (16 October 2026)

- Interest on overdue bills, stock alerts on Telegram, e-invoice QR and e-way bill on invoices, Hindi in PDFs.

## 2.8 (16 October 2026)

- Stock combined across godowns. Opening stock from Tally's month-end figures.

## 2.7 (16 October 2026)

- **Balance Sheet and Profit & Loss** in Tally's own layout.
- Only the vouchers that changed are sent, not whole months.

## 2.6 (16 October 2026)

- Sync automatic, manual (**Sync now**) or paused.
- A brighter look, with separate phone and computer layouts.
- Stock with opening, in, out and closing for any period. Ledgers open on this month.
- Voucher types combined under their Tally heading, or one at a time.

## 2.5 (15 October 2026)

- **Staff logins** that see only what you allow.
- **Receipts, payments and sales orders from the phone**, with your approval for staff entries.

## 2.4 (15 October 2026)

- Balance Sheet, cash and bank book, follow-up list with notes and promised dates, nightly backups.

## 2.3 (15 October 2026)

- Cancelled vouchers handled, faster sync, sales analysis, Excel downloads, Telegram morning summary and payment alerts.

## 2.0 to 2.2 (15 October 2026)

- **Sales by day**, ledgers sorted by name, balance or activity.
- *This year* means the current financial year.
- Change password and delete old data in Settings; a Sync check screen.
- Fixes for Tally add-on fields, emoji in Tally data, and Tallys whose Day Book ignores dates.
- Orders and memorandum vouchers kept out of balances and stock.

## 1.x (15 October 2026)

- First release:
  - ledgers, vouchers, bill-wise outstanding with ageing, stock, GST summary and Day Book on the phone;
  - Tally-style Tax Invoice, voucher and Ledger Account PDFs;
  - an Unraid template.
