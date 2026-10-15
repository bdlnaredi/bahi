# Diagnose.ps1 - finds out why some vouchers don't reach Bahi.
# Reports only counts and dates (no party names or amounts). Result is saved to your Desktop.
$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desk = [Environment]::GetFolderPath("Desktop"); if (-not $desk) { $desk = $Here }
$Out = Join-Path $desk "Bahi-Diagnosis.txt"
$Cfg = Get-Content (Join-Path $Here "TallySync.config.json") -Raw | ConvertFrom-Json
$Tally = if ($Cfg.TallyUrl) { $Cfg.TallyUrl } else { "http://localhost:9000" }
$Inv = [System.Globalization.CultureInfo]::InvariantCulture
$lines = New-Object System.Collections.ArrayList
function Say([string]$s) { [void]$lines.Add($s); Write-Host $s }

function Raw([string]$xml) {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Content-Type", "text/xml;charset=utf-8")
    $b = $wc.UploadData($Tally, "POST", [System.Text.Encoding]::UTF8.GetBytes($xml))
    $t = [System.Text.Encoding]::UTF8.GetString($b)
    $ev = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) if ([int]$m.Groups[1].Value -lt 32) { "" } else { $m.Value } }
    $t = [regex]::Replace($t, '&#([0-9]+);', $ev)
    return [regex]::Replace($t, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
}
function Esc([string]$s) { [System.Security.SecurityElement]::Escape($s) }
function Static-Vars([string]$co, [string]$f, [string]$t) {
    "<SVEXPORTFORMAT>`$`$SysName:XML</SVEXPORTFORMAT><SVCURRENTCOMPANY>" + (Esc $co) + "</SVCURRENTCOMPANY>" +
    "<SVFROMDATE TYPE=`"Date`">$f</SVFROMDATE><SVTODATE TYPE=`"Date`">$t</SVTODATE>"
}
function Dates([string]$text) {
    $ds = @()
    foreach ($m in [regex]::Matches($text, '<VOUCHER[ >][\s\S]*?<DATE[^>]*>([^<]+)</DATE>')) {
        $s = $m.Groups[1].Value.Trim(); $d = [datetime]::MinValue
        if ($s -match '^\d{8}$') { $d = [datetime]::ParseExact($s, "yyyyMMdd", $Inv) }
        elseif (-not [datetime]::TryParseExact($s, [string[]]@("d-MMM-yyyy","d-MMM-yy"), $Inv, 0, [ref]$d)) { continue }
        $ds += $d
    }
    return ,$ds
}
function Report([string]$label, [string]$xml, [datetime]$a, [datetime]$b) {
    try {
        $t = Raw $xml
        $ds = Dates $t
        $in = @($ds | Where-Object { $_ -ge $a -and $_ -le $b }).Count
        $range = if ($ds.Count) { ($ds | Measure-Object -Minimum -Maximum) } else { $null }
        $err = if ($t -match '<LINEERROR>([^<]*)') { "  ERROR: " + $Matches[1] } else { "" }
        $mm = if ($range) { "  dates " + $range.Minimum.ToString("yyyy-MM-dd") + ".." + $range.Maximum.ToString("yyyy-MM-dd") } else { "" }
        Say ("    {0,-34} got {1,5}, inside the month {2,5}{3}{4}" -f $label, $ds.Count, $in, $mm, $err)
    } catch { Say ("    {0,-34} FAILED: {1}" -f $label, $_.Exception.Message) }
}

Say ("Bahi diagnosis  " + (Get-Date -Format "yyyy-MM-dd HH:mm") + "   Tally: $Tally")
$cx = ""
try { $cx = Raw "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>DGCo</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>`$`$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME=`"DGCo`" ISMODIFY=`"No`"><TYPE>Company</TYPE><FETCH>Name, StartingFrom, BooksFrom, AltVchId</FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>" }
catch { Say ("Tally is not reachable on $Tally - open TallyPrime with your company and run this again. (" + $_.Exception.Message + ")") }
$cos = @([regex]::Matches($cx, '<COMPANY NAME="([^"]*)"[\s\S]*?</COMPANY>') | ForEach-Object { $_ })
Say ("Companies open in Tally: " + $cos.Count)
foreach ($c in $cos) {
    $blk = $c.Value
    $nm = [System.Net.WebUtility]::HtmlDecode($c.Groups[1].Value)
    $sf = if ($blk -match '<STARTINGFROM[^>]*>([^<]*)') { $Matches[1] } else { "?" }
    $bf = if ($blk -match '<BOOKSFROM[^>]*>([^<]*)') { $Matches[1] } else { "?" }
    Say ""
    Say ("Company: $nm   (books from $bf, period starts $sf)")
    $today = Get-Date
    foreach ($mo in @($today, $today.AddMonths(-1), $today.AddYears(-1))) {
        $a = Get-Date -Year $mo.Year -Month $mo.Month -Day 1; $a = $a.Date; $b = $a.AddMonths(1).AddDays(-1)
        Say ("  Month " + $a.ToString("MMM yyyy") + ":")
        $f1 = $a.ToString("d-MMM-yyyy", $Inv); $t1 = $b.ToString("d-MMM-yyyy", $Inv)
        $f2 = $a.ToString("yyyyMMdd"); $t2 = $b.ToString("yyyyMMdd")
        $db = "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Day Book</ID></HEADER><BODY><DESC><STATICVARIABLES>{0}<EXPLODEFLAG>Yes</EXPLODEFLAG></STATICVARIABLES></DESC></BODY></ENVELOPE>"
        Report "Day Book (1-Apr-2026 dates)" ($db -f (Static-Vars $nm $f1 $t1)) $a $b
        Report "Day Book (20260401 dates)" ($db -f (Static-Vars $nm $f2 $t2)) $a $b
        $col = "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>DGV</ID></HEADER><BODY><DESC><STATICVARIABLES>{0}</STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME=`"DGV`" ISMODIFY=`"No`"><TYPE>Voucher</TYPE><FETCH>Date</FETCH>{1}</COLLECTION>{2}</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
        $flt = "<SYSTEM TYPE=`"Formulae`" NAME=`"DGIn`">`$Date &gt;= ##SVFromDate AND `$Date &lt;= ##SVToDate</SYSTEM>"
        Report "Collection with date filter" ($col -f (Static-Vars $nm $f1 $t1), "<FILTER>DGIn</FILTER>", $flt) $a $b
        Report "Collection, no filter" ($col -f (Static-Vars $nm $f1 $t1), "", "") $a $b
    }
}

Say ""
Say "What the Bahi server holds (vouchers per month):"
try {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Authorization", "Bearer " + $Cfg.SyncToken)
    $st = $wc.DownloadString($Cfg.ServerUrl.TrimEnd("/") + "/agent/stats") | ConvertFrom-Json
    foreach ($co in $st.companies) {
        Say ("  " + $co.name + "  synced range " + $co.from_date + " to " + $co.to_date + $(if ($co.keep_from) { ", keeping from " + $co.keep_from } else { "" }))
        Say ("    " + (($co.months | ForEach-Object { $_.m + ":" + $_.n }) -join "  "))
    }
} catch { Say ("  Could not read (update the server to the latest version): " + $_.Exception.Message) }

Say ""
Say "Last lines of TallySync.log:"
$log = Join-Path $Here "TallySync.log"
if (Test-Path $log) { Get-Content $log -Tail 15 | ForEach-Object { Say ("  " + $_) } } else { Say "  (no log yet)" }
$lines | Set-Content $Out -Encoding UTF8
Write-Host ""
Write-Host "Saved to $Out - copy its text into the chat." -ForegroundColor Cyan
