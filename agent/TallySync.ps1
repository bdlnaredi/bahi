# TallySync.ps1 - copies data from TallyPrime to your Tally Mobile server.
# Runs every few minutes from Windows Task Scheduler (set up by Setup.bat).
# Usage:  TallySync.ps1            normal run (skips if nothing changed in Tally)
#         TallySync.ps1 -Force     always send everything
param([switch]$Force, [switch]$Verbose)

$ErrorActionPreference = "Stop"
$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$CfgPath = Join-Path $Here "TallySync.config.json"
$LogPath = Join-Path $Here "TallySync.log"

function Log([string]$msg, [string]$color = "Gray") {
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "  " + $msg
    try {
        if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) {
            Move-Item $LogPath ($LogPath + ".old") -Force
        }
        Add-Content -Path $LogPath -Value $line -Encoding UTF8
    } catch {}
    Write-Host $line -ForegroundColor $color
}

if (-not (Test-Path $CfgPath)) { Log "Config file missing. Run Setup.bat first." "Red"; exit 2 }
$Cfg = Get-Content $CfgPath -Raw | ConvertFrom-Json
$Server = $Cfg.ServerUrl.TrimEnd("/")
$Tally  = if ($Cfg.TallyUrl) { $Cfg.TallyUrl } else { "http://localhost:9000" }

# Financial year (India): April to March
$today = Get-Date
$fyStartYear = if ($today.Month -ge 4) { $today.Year } else { $today.Year - 1 }
$FromDate = if ($Cfg.FromDate) { [datetime]::ParseExact($Cfg.FromDate, "yyyy-MM-dd", $null) } else { Get-Date -Year $fyStartYear -Month 4 -Day 1 }
$ToDate   = Get-Date -Year ($fyStartYear + 1) -Month 3 -Day 31
$FromDate = $FromDate.Date; $ToDate = $ToDate.Date

function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }
function TDate([datetime]$d) { return $d.ToString("yyyyMMdd") }

function Tally-Raw([string]$xml) {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Content-Type", "text/xml;charset=utf-8")
    return $wc.UploadData($Tally, "POST", [System.Text.Encoding]::UTF8.GetBytes($xml))
}

function Static-Vars([string]$company, [datetime]$from, [datetime]$to) {
    $s = "<SVEXPORTFORMAT>`$`$SysName:XML</SVEXPORTFORMAT>"
    if ($company) { $s += "<SVCURRENTCOMPANY>" + (Esc $company) + "</SVCURRENTCOMPANY>" }
    if ($from)    { $s += "<SVFROMDATE TYPE=`"Date`">" + (TDate $from) + "</SVFROMDATE>" }
    if ($to)      { $s += "<SVTODATE TYPE=`"Date`">" + (TDate $to) + "</SVTODATE>" }
    return $s
}

function Collection-Xml([string]$id, [string]$type, [string]$fetch, [string]$company) {
    $sv = Static-Vars $company $FromDate $ToDate
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>$id</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES><TDL><TDLMESSAGE>" +
           "<COLLECTION NAME=`"$id`" ISMODIFY=`"No`"><TYPE>$type</TYPE><FETCH>$fetch</FETCH></COLLECTION>" +
           "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
}

function DayBook-Xml([string]$company, [datetime]$from, [datetime]$to) {
    $sv = Static-Vars $company $from $to
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Day Book</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv<EXPLODEFLAG>Yes</EXPLODEFLAG></STATICVARIABLES></DESC></BODY></ENVELOPE>"
}

function Report-Xml([string]$report, [string]$company, [datetime]$from, [datetime]$to) {
    $sv = Static-Vars $company $from $to
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>$report</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES></DESC></BODY></ENVELOPE>"
}

function Gzip([byte[]]$data) {
    $ms = New-Object System.IO.MemoryStream
    $gz = New-Object System.IO.Compression.GZipStream($ms, [System.IO.Compression.CompressionMode]::Compress)
    $gz.Write($data, 0, $data.Length); $gz.Close()
    return $ms.ToArray()
}

function Server-Client {
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Authorization", "Bearer " + $Cfg.SyncToken)
    $wc.Encoding = [System.Text.Encoding]::UTF8
    return $wc
}

function Server-Json([string]$method, [string]$path, $obj) {
    $wc = Server-Client
    $wc.Headers.Add("Content-Type", "application/json")
    if ($method -eq "GET") { $res = $wc.DownloadString($Server + $path) }
    else { $res = $wc.UploadString($Server + $path, "POST", ($obj | ConvertTo-Json -Compress -Depth 5)) }
    return $res | ConvertFrom-Json
}

function Send-Part([string]$run, [string]$kind, [byte[]]$data) {
    $wc = Server-Client
    $wc.Headers.Add("Content-Type", "application/octet-stream")
    $wc.Headers.Add("X-Gzip", "1")
    [void]$wc.UploadData("$Server/agent/part?run=$run&kind=$kind", "POST", (Gzip $data))
}

function Read-Companies {
    $raw = Tally-Raw (Collection-Xml "TMCompanies" "Company" "Name, AltVchId, AltMstId" "")
    $text = [System.Text.Encoding]::UTF8.GetString($raw)
    $eval = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) if ([int]$m.Groups[1].Value -lt 32) { "" } else { $m.Value } }
    $text = [regex]::Replace($text, '&#([0-9]+);', $eval)
    $text = [regex]::Replace($text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
    [xml]$x = $text
    $list = @()
    foreach ($n in $x.SelectNodes("//COMPANY")) {
        $name = $n.GetAttribute("NAME")
        if (-not $name) { $nn = $n.SelectSingleNode("NAME"); if ($nn) { $name = $nn.InnerText } }
        $av = $n.SelectSingleNode("ALTVCHID"); $am = $n.SelectSingleNode("ALTMSTID")
        if ($name) {
            $list += [pscustomobject]@{
                Name = $name.Trim()
                AltVch = $(if ($av) { $av.InnerText.Trim() } else { "" })
                AltMst = $(if ($am) { $am.InnerText.Trim() } else { "" })
            }
        }
    }
    return $list
}

# ------------------------------------------------------------------ main
try { $companies = @(Read-Companies) }
catch { Log ("Tally is not reachable on $Tally - is TallyPrime open? (" + $_.Exception.Message + ")") "Yellow"; exit 3 }

if ($companies.Count -eq 0) { Log "Tally is open but no company is loaded." "Yellow"; exit 3 }

$fromIso = $FromDate.ToString("yyyy-MM-dd"); $toIso = $ToDate.ToString("yyyy-MM-dd")
$exitCode = 0

foreach ($co in $companies) {
    try {
        $state = Server-Json "GET" ("/agent/state?company=" + [uri]::EscapeDataString($co.Name)) $null
        $unchanged = $co.AltVch -and $co.AltMst -and ($state.alt_vch -eq $co.AltVch) -and
                     ($state.alt_mst -eq $co.AltMst) -and ($state.from_date -eq $fromIso)
        if ($unchanged -and -not $Force) {
            if ($Verbose) { Log ("No changes in " + $co.Name) }
            continue
        }
        $t0 = Get-Date
        $run = [guid]::NewGuid().ToString("N")
        Log ("Syncing " + $co.Name + " (" + $fromIso + " to " + $toIso + ") ...") "Cyan"

        Send-Part $run "groups"  (Tally-Raw (Collection-Xml "TMGroups" "Group" "Name, Parent" $co.Name))
        Send-Part $run "vtypes"  (Tally-Raw (Collection-Xml "TMVchTypes" "VoucherType" "Name, Parent" $co.Name))
        Send-Part $run "ledgers" (Tally-Raw (Collection-Xml "TMLedgers" "Ledger" `
            "Name, Parent, OpeningBalance, ClosingBalance, LedgerPhone, LedgerMobile, Email, PartyGSTIN, TaxType, GSTDutyHead" $co.Name))
        Send-Part $run "stock"   (Tally-Raw (Collection-Xml "TMStock" "StockItem" `
            "Name, Parent, BaseUnits, OpeningBalance, OpeningValue, ClosingBalance, ClosingValue, ClosingRate" $co.Name))

        # Bill-wise outstanding as Tally calculates it (skipped quietly if this Tally can't export it)
        foreach ($r in @(@("bills_rec", "Bills Receivable"), @("bills_pay", "Bills Payable"))) {
            try { Send-Part $run $r[0] (Tally-Raw (Report-Xml $r[1] $co.Name $FromDate $today.Date)) }
            catch { Log ("Could not read " + $r[1] + " from Tally: " + $_.Exception.Message) "Yellow" }
        }

        # Vouchers, one month at a time to keep each request small
        $m = Get-Date -Year $FromDate.Year -Month $FromDate.Month -Day 1
        while ($m -le $ToDate) {
            $mEnd = $m.AddMonths(1).AddDays(-1)
            $a = if ($m -lt $FromDate) { $FromDate } else { $m }
            $b = if ($mEnd -gt $ToDate) { $ToDate } else { $mEnd }
            Send-Part $run "daybook" (Tally-Raw (DayBook-Xml $co.Name $a $b))
            $m = $m.AddMonths(1)
        }

        $res = Server-Json "POST" "/agent/commit" @{
            run = $run; company = $co.Name; from = $fromIso; to = $toIso; alt_vch = $co.AltVch; alt_mst = $co.AltMst
        }
        $secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        Log ("Done: " + $res.ledgers + " ledgers, " + $res.stock + " stock items, " + $res.vouchers +
             " vouchers in $secs s") "Green"
        if ($res.unbalanced -gt 0) { Log ("Warning: " + $res.unbalanced + " vouchers did not balance - tell Claude") "Yellow" }
    } catch {
        $exitCode = 1
        $detail = $_.Exception.Message
        if ($_.Exception.InnerException) { $detail += " / " + $_.Exception.InnerException.Message }
        Log ("Sync failed for " + $co.Name + ": " + $detail) "Red"
    }
}

try { [void](Server-Json "POST" "/agent/heartbeat" @{ companies = @($companies | ForEach-Object { $_.Name }) }) } catch {}
exit $exitCode
