# Save-Stock.ps1 - saves what Tally reports for stock as at one date, three ways, into stock-sample.xml,
# so a difference in opening stock can be traced. Only talks to Tally on this PC.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tally = "http://localhost:9000"; $From = "1-Apr-2000"
try {
    $cfg = Get-Content (Join-Path $Here "TallySync.config.json") -Raw | ConvertFrom-Json
    if ($cfg.TallyUrl) { $Tally = $cfg.TallyUrl }
    if ($cfg.FromDate) { $From = ([datetime]::ParseExact($cfg.FromDate, "yyyy-MM-dd", $null)).ToString("d-MMM-yyyy", [Globalization.CultureInfo]::InvariantCulture) }
} catch {}
function Tally-Text([string]$xml) {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Content-Type", "text/xml;charset=utf-8")
    return [System.Text.Encoding]::UTF8.GetString($wc.UploadData($Tally, "POST", [System.Text.Encoding]::UTF8.GetBytes($xml)))
}
function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }

Write-Host "Save stock figures from Tally (for checking opening stock)" -ForegroundColor Cyan
$d = (Read-Host "Stock as at which date? (e.g. 31-03-2026 for the opening on 1 April 2026)").Trim()
try { $day = [datetime]::ParseExact($d, "dd-MM-yyyy", $null) } catch { Write-Host "Type the date like 31-03-2026." -ForegroundColor Yellow; exit 1 }
$co = (Read-Host "Company name (press Enter for the company open in Tally)").Trim()
$to = $day.ToString("d-MMM-yyyy", [Globalization.CultureInfo]::InvariantCulture)
$fy = (Get-Date -Year $(if ($day.Month -ge 4) { $day.Year } else { $day.Year - 1 }) -Month 4 -Day 1).ToString("d-MMM-yyyy", [Globalization.CultureInfo]::InvariantCulture)
function SV([string]$f) {
    $s = "<SVEXPORTFORMAT>`$`$SysName:XML</SVEXPORTFORMAT><SVFROMDATE TYPE=`"Date`">$f</SVFROMDATE><SVTODATE TYPE=`"Date`">$to</SVTODATE><EXPLODEFLAG>Yes</EXPLODEFLAG>"
    if ($co) { $s += "<SVCURRENTCOMPANY>" + (Esc $co) + "</SVCURRENTCOMPANY>" }
    return $s
}
$coll = { param($f) "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>TMStockAt</ID></HEADER>" +
          "<BODY><DESC><STATICVARIABLES>" + (SV $f) + "</STATICVARIABLES><TDL><TDLMESSAGE>" +
          "<COLLECTION NAME=`"TMStockAt`" ISMODIFY=`"No`"><TYPE>StockItem</TYPE><FETCH>Name, Parent, BaseUnits, OpeningBalance, OpeningValue, ClosingBalance, ClosingValue, ClosingRate, BatchAllocations</FETCH></COLLECTION>" +
          "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>" }
$report = "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Stock Summary</ID></HEADER>" +
          "<BODY><DESC><STATICVARIABLES>" + (SV $fy) + "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
$parts = @()
foreach ($pair in @(@("collection, from the sync start ($From) to $to", (& $coll $From)),
                    @("collection, from the financial year start ($fy) to $to", (& $coll $fy)),
                    @("Stock Summary report, $fy to $to", $report))) {
    try { $parts += "<!-- " + $pair[0] + " -->`r`n" + (Tally-Text $pair[1]) }
    catch { $parts += "<!-- " + $pair[0] + ": " + $_.Exception.Message + " -->" }
}
$out = Join-Path $Here "stock-sample.xml"
Set-Content -Path $out -Value ($parts -join "`r`n`r`n") -Encoding UTF8
Write-Host ("Saved $out (" + (Get-Item $out).Length + " bytes).") -ForegroundColor Green
Write-Host "Attach it in the chat with Claude, with the opening stock Tally shows for one or two items."
