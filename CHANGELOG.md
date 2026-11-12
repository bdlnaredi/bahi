# Changelog

Everything that changed in Bahi, newest first. The version is the server version shown in the app under Settings. "Tally PC" is the sync on the PC that runs TallyPrime (Bahi Sync), which updates itself from the server.

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
