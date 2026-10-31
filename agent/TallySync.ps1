# TallySync.ps1 - copies data from TallyPrime to your Tally Mobile server.
# Runs every few minutes from Windows Task Scheduler (set up by Setup.bat).
# Usage:  TallySync.ps1            normal run (skips if nothing changed in Tally)
#         TallySync.ps1 -Force     always send everything
#         TallySync.ps1 -Now       check Tally for changes right away (the Bahi Sync app's Sync now)
param([switch]$Force, [switch]$Verbose, [switch]$Now)
$AgentVersion = "3.11"

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

# ------------------------------------------------------------------ self-update
# The server carries the latest Tally PC files. When its version differs from this one, download them,
# check each file's SHA-256, replace them, and run the new version straight away.
function Self-Update {
    if ($env:BAHI_JUST_UPDATED -eq "1") { return }
    try {
        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add("Authorization", "Bearer " + $Cfg.SyncToken)
        $u = $wc.DownloadString($Server + "/agent/update") | ConvertFrom-Json
    } catch { return }                                   # an older server without updates
    if (-not $u.version -or -not $u.auto) { return }
    # only ever move forward: a server not updated yet must not swap newer files back to its older ones
    try { if ([version]$u.version -le [version]$AgentVersion) { return } } catch { if ($u.version -eq $AgentVersion) { return } }
    $tmp = Join-Path $Here (".update-" + $PID)          # this run's own folder
    try {
        if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
        New-Item -ItemType Directory -Path $tmp -Force | Out-Null
        foreach ($f in @($u.files)) {
            if ($f.name -notmatch '^[A-Za-z0-9_.-]+\.(ps1|bat|vbs)$') { throw "unexpected file name" }
            $wc = New-Object System.Net.WebClient
            $wc.Headers.Add("Authorization", "Bearer " + $Cfg.SyncToken)
            $bytes = $wc.DownloadData($Server + "/agent/update/file?name=" + [uri]::EscapeDataString($f.name))
            $sha = [System.Security.Cryptography.SHA256]::Create()
            $hash = -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
            if ($hash -ne $f.sha256) { throw ("download of " + $f.name + " was damaged") }
            [System.IO.File]::WriteAllBytes((Join-Path $tmp $f.name), $bytes)
        }
        foreach ($f in @($u.files)) { Move-Item -Force (Join-Path $tmp $f.name) (Join-Path $Here $f.name) }
        Remove-Item $tmp -Recurse -Force
    } catch {
        Log ("Could not update the Tally PC files: " + $_.Exception.Message + " - carrying on with version $AgentVersion") "Yellow"
        try { Remove-Item $tmp -Recurse -Force } catch {}
        return
    }
    Log ("Tally PC files updated from version $AgentVersion to " + $u.version) "Green"
    $env:BAHI_JUST_UPDATED = "1"
    $argv = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Here "TallySync.ps1"))
    if ($Force) { $argv += "-Force" }
    if ($Now) { $argv += "-Now" }
    if ($Verbose) { $argv += "-Verbose" }
    $exe = (Get-Process -Id $PID).Path
    # hand the one-sync-at-a-time lock to the new version before starting it
    try { Remove-Item $RunFile -ErrorAction SilentlyContinue } catch {}
    try { $script:Mutex.ReleaseMutex() } catch {}
    & $exe @argv
    exit $LASTEXITCODE
}

# Financial year (India): April to March
$today = Get-Date
$fyStartYear = if ($today.Month -ge 4) { $today.Year } else { $today.Year - 1 }
$FromDate = if ($Cfg.FromDate) { [datetime]::ParseExact($Cfg.FromDate, "yyyy-MM-dd", $null) } else { Get-Date -Year $fyStartYear -Month 4 -Day 1 }
$ToDate   = Get-Date -Year ($fyStartYear + 1) -Month 3 -Day 31
$FromDate = $FromDate.Date; $ToDate = $ToDate.Date

# One sync at a time: a run that starts while another is still going (a long first sync, Sync-Now pressed)
# leaves quietly, so Tally isn't asked for everything twice at once
$script:Mutex = New-Object System.Threading.Mutex($false, "Global\BahiTallySync")
$RunFile = Join-Path $Here "TallySync.running"
$owned = $false
try { $owned = $script:Mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) {
    # A run that has gone on far longer than any sync takes is stuck (the PC slept mid-sync, the network
    # dropped): stop it and take over, so one stuck run can't stop syncing for good
    $run0 = $null
    try { $run0 = Get-Content $RunFile -Raw | ConvertFrom-Json } catch {}
    $age = if ($run0) { ((Get-Date) - [datetime]::Parse($run0.started, [System.Globalization.CultureInfo]::InvariantCulture)).TotalMinutes } else { 0 }
    if ($run0 -and $age -gt 90 -and [int]$run0.pid -ne $PID) {
        Log ("The sync started " + [math]::Round($age) + " minutes ago is stuck - stopping it and starting again.") "Yellow"
        try { Stop-Process -Id ([int]$run0.pid) -Force -ErrorAction Stop } catch {}
        try { $owned = $script:Mutex.WaitOne(15000) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
    }
    if (-not $owned) {
        # say so in the log now and then (not every 2 minutes), so a long wait can be seen
        $skipFile = Join-Path $Here "TallySync.skipped"
        $lastSkip = 0; try { $lastSkip = [double](Get-Content $skipFile -Raw) } catch {}
        $nowS = [double](Get-Date -UFormat %s)
        if ($Force -or $Verbose -or ($nowS - $lastSkip -gt 1800)) {
            $since0 = if ($run0) { " (running since " + $run0.started + ")" } else { "" }
            Log ("Another sync is still running on this PC" + $since0 + " - this one is skipped.") "Yellow"
            try { Set-Content $skipFile $nowS } catch {}
        }
        exit 0
    }
}
function End-Run([int]$code) {
    try { Remove-Item $RunFile -ErrorAction SilentlyContinue } catch {}
    exit $code
}
try { @{ pid = $PID; started = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss", [System.Globalization.CultureInfo]::InvariantCulture) } | ConvertTo-Json | Set-Content $RunFile } catch {}
# updating the files happens only here, inside the lock, so two runs can't update at the same time
Self-Update

function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }
# Tally's own date style (1-Apr-2026) - understood by every TallyPrime release
function TDate([datetime]$d) { return $d.ToString("d-MMM-yyyy", [System.Globalization.CultureInfo]::InvariantCulture) }

function Assert-Safe([string]$xml) {
    # Bahi must never delete or change anything already in Tally. Every request is checked here, just before
    # it goes to Tally; anything that isn't a plain read, or the creation of new vouchers, is refused.
    $u = $xml.ToUpperInvariant()
    $req = [regex]::Match($u, '<TALLYREQUEST>\s*([A-Z ]+?)\s*</TALLYREQUEST>').Groups[1].Value
    if ($req -eq "EXPORT") {
        if ($u -match 'ACTION\s*=|<ACTION[\s>]|IMPORT|<DELETE|<ALTER|<CANCEL|EXECUTE') { throw "Blocked: a read request that tries to act on Tally" }
        return
    }
    if ($req -eq "IMPORT DATA") {
        if ([regex]::Match($u, '<REPORTNAME>\s*(.*?)\s*</REPORTNAME>').Groups[1].Value -ne "VOUCHERS") { throw "Blocked: only vouchers may be added to Tally" }
        $actions = @([regex]::Matches($u, 'ACTION\s*=\s*"([^"]*)"') | ForEach-Object { $_.Groups[1].Value })
        $objects = @([regex]::Matches($u, '<TALLYMESSAGE[^>]*>\s*<([A-Z.]+)') | ForEach-Object { $_.Groups[1].Value })
        if (-not $actions.Count -or ($actions | Where-Object { $_ -ne "CREATE" })) { throw "Blocked: an entry that would change or delete something in Tally" }
        if ($objects | Where-Object { $_ -ne "VOUCHER" }) { throw "Blocked: only new vouchers may be added to Tally" }
        if ($u -match '<(GUID|REMOTEID|MASTERID|ALTERID|VOUCHERKEY|VCHKEY|ISDELETED|ISCANCELLED|IMPORTDUPS)[\s>]|REMOTEID\s*=|VCHKEY\s*=|TAGNAME|TAGVALUE|<TDL|<DELETE|<ALTER|<CANCEL') {
            throw "Blocked: an entry that points at something already in Tally" }
        return
    }
    throw "Blocked: unknown request to Tally"
}

function Tally-Raw([string]$xml) {
    Assert-Safe $xml
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

function Masters-Xml([string]$accountType, [string]$company) {
    $sv = Static-Vars $company $FromDate $ToDate
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>List of Accounts</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv<ACCOUNTTYPE>$accountType</ACCOUNTTYPE></STATICVARIABLES></DESC></BODY></ENVELOPE>"
}

$VchFields = @(
    "Date", "GUID", "AlterID", "VoucherTypeName", "VoucherNumber", "PartyLedgerName", "PartyGSTIN", "Narration", "Reference",
    "ReferenceDate", "IsCancelled", "IsOptional", "IsDeleted", "PlaceOfSupply", "StateName", "BasicBuyerName",
    "BasicDueDateOfPymt", "BasicShipDocumentNo", "BasicShippedBy", "BasicFinalDestination", "BasicOrderRef",
    "AllLedgerEntries.LedgerName", "AllLedgerEntries.Amount", "AllLedgerEntries.IsDeemedPositive",
    "AllLedgerEntries.BillAllocations.Name", "AllLedgerEntries.BillAllocations.BillType",
    "AllLedgerEntries.BillAllocations.Amount", "AllLedgerEntries.BillAllocations.BillCreditPeriod",
    "LedgerEntries.LedgerName", "LedgerEntries.Amount", "LedgerEntries.IsDeemedPositive",
    "LedgerEntries.BillAllocations.Name", "LedgerEntries.BillAllocations.BillType",
    "LedgerEntries.BillAllocations.Amount", "LedgerEntries.BillAllocations.BillCreditPeriod",
    "AllInventoryEntries.StockItemName", "AllInventoryEntries.ActualQty", "AllInventoryEntries.BilledQty",
    "AllInventoryEntries.BatchAllocations.TrackingNumber", "AllInventoryEntries.BatchAllocations.GodownName",
    "AllInventoryEntries.BatchAllocations.ActualQty",
    "InventoryEntriesIn.BatchAllocations.GodownName", "InventoryEntriesIn.BatchAllocations.ActualQty",
    "InventoryEntriesOut.BatchAllocations.GodownName", "InventoryEntriesOut.BatchAllocations.ActualQty",
    "AllInventoryEntries.Rate", "AllInventoryEntries.Amount", "AllInventoryEntries.IsDeemedPositive",
    "AllInventoryEntries.Discount", "AllInventoryEntries.AccountingAllocations.LedgerName",
    "AllInventoryEntries.AccountingAllocations.Amount",
    "InventoryEntriesIn.StockItemName", "InventoryEntriesIn.ActualQty", "InventoryEntriesIn.Rate", "InventoryEntriesIn.Amount",
    "InventoryEntriesOut.StockItemName", "InventoryEntriesOut.ActualQty", "InventoryEntriesOut.Rate", "InventoryEntriesOut.Amount"
) -join ", "

# Vouchers as a collection, limited to the period with an explicit date filter
function VchCollection-Xml([string]$company, [datetime]$from, [datetime]$to, [string]$fetch) {
    $sv = Static-Vars $company $from $to
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>TMVouchers</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES><TDL><TDLMESSAGE>" +
           "<COLLECTION NAME=`"TMVouchers`" ISMODIFY=`"No`"><TYPE>Voucher</TYPE><FETCH>$fetch</FETCH><FILTER>TMInPeriod</FILTER></COLLECTION>" +
           "<SYSTEM TYPE=`"Formulae`" NAME=`"TMInPeriod`">`$Date &gt;= ##SVFromDate AND `$Date &lt;= ##SVToDate</SYSTEM>" +
           "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
}

# e-invoice (IRN, Ack, signed QR) and e-way bill details of the vouchers being sent. Kept separate so a
# Tally release that doesn't know one of these names can't stop the sync.
$EinvFields = "GUID, IRN, IRNAckNo, IRNAckDate, IRNQRCode, EWayBillDetails"
function Einv-Xml([string]$company, [datetime]$from, [datetime]$to, [string[]]$guids) {
    $sv = Static-Vars $company $from $to
    $cond = "`$Date &gt;= ##SVFromDate AND `$Date &lt;= ##SVToDate"
    if ($guids) { $cond = ($guids | ForEach-Object { "`$GUID = `"" + ($_ -replace '[^A-Za-z0-9\-]', '') + "`"" }) -join " OR " }
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>TMEinv</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES><TDL><TDLMESSAGE>" +
           "<COLLECTION NAME=`"TMEinv`" ISMODIFY=`"No`"><TYPE>Voucher</TYPE><FETCH>$EinvFields</FETCH><FILTER>TMEinvF</FILTER></COLLECTION>" +
           "<SYSTEM TYPE=`"Formulae`" NAME=`"TMEinvF`">$cond</SYSTEM>" +
           "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
}
function Send-Einv($run, [string]$company, [datetime]$from, [datetime]$to, [string[]]$guids) {
    try { Send-Part $run "einv" (Tally-Raw (Einv-Xml $company $from $to $guids)) }
    catch { if ($Verbose) { Log ("e-invoice details not read: " + $_.Exception.Message) "Gray" } }
}

# Every stock item's (or ledger's) balance as Tally has it at the end of one day. The period starts at the
# company's books beginning, so Tally counts everything up to that day. For the day before the books begin,
# Tally's own opening balance is the figure (a period ending before it starts gives wrong numbers).
function BalanceAt-Xml([string]$company, [string]$type, [datetime]$books, [datetime]$day) {
    $opening = $day -lt $books
    $fetch = if ($type -eq "StockItem") { if ($opening) { "Name, OpeningBalance, OpeningValue" } else { "Name, ClosingBalance, ClosingValue" } }
             else { if ($opening) { "Name, OpeningBalance" } else { "Name, ClosingBalance" } }
    $sv = if ($opening) { Static-Vars $company $books $books } else { Static-Vars $company $books $day }
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>TMAt</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES><TDL><TDLMESSAGE>" +
           "<COLLECTION NAME=`"TMAt`" ISMODIFY=`"No`"><TYPE>$type</TYPE><FETCH>$fetch</FETCH></COLLECTION>" +
           "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
}

# Only the vouchers with these GUIDs (what was created or changed since the last sync)
function VchGuid-Xml([string]$company, [string[]]$guids, [string]$fetch) {
    $sv = Static-Vars $company $FromDate $ToDate
    $cond = ($guids | ForEach-Object { "`$GUID = `"" + ($_ -replace '[^A-Za-z0-9\-]', '') + "`"" }) -join " OR "
    return "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>TMVouchers</ID></HEADER>" +
           "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES><TDL><TDLMESSAGE>" +
           "<COLLECTION NAME=`"TMVouchers`" ISMODIFY=`"No`"><TYPE>Voucher</TYPE><FETCH>$fetch</FETCH><FILTER>TMPicked</FILTER></COLLECTION>" +
           "<SYSTEM TYPE=`"Formulae`" NAME=`"TMPicked`">$cond</SYSTEM>" +
           "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
}

function Parse-Xml([byte[]]$raw) {
    try {
        $text = [System.Text.Encoding]::UTF8.GetString($raw)
        # drop character references Windows' XML reader rejects (control codes, emoji halves)
        $eval = [System.Text.RegularExpressions.MatchEvaluator]{ param($m)
            $s = $m.Groups[1].Value
            $n = if ($s.StartsWith("x") -or $s.StartsWith("X")) { [Convert]::ToInt64($s.Substring(1), 16) } else { [int64]$s }
            if (($n -lt 32 -and $n -ne 9 -and $n -ne 10 -and $n -ne 13) -or ($n -ge 0xD800 -and $n -le 0xDFFF) -or $n -eq 0xFFFE -or $n -eq 0xFFFF -or $n -gt 0x10FFFF) { "" } else { $m.Value }
        }
        $text = [regex]::Replace($text, '&#(x[0-9a-fA-F]+|[0-9]+);', $eval)
        $text = [regex]::Replace($text, '[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]', '')
        # add-on fields like <UDF:FIELD> arrive without their namespace declaration; use plain names
        $tagFix = [System.Text.RegularExpressions.MatchEvaluator]{ param($m)
            $t = [regex]::Replace($m.Value, '\sxmlns(:[\w.-]+)?\s*=\s*("[^"]*"|''[^'']*'')', '')
            $t = [regex]::Replace($t, '<(/?)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)', '<$1$2_$3')
            [regex]::Replace($t, '(\s)([A-Za-z_][\w.-]*):([A-Za-z_][\w.-]*)(\s*=)', '$1$2_$3$4')
        }
        $text = [regex]::Replace($text, '<[^<>]+>', $tagFix)
        return [xml]$text
    } catch { return $null }
}

# Counting without an XML reader - used if a reply can't be parsed, so data is never dropped for that reason
function Count-Vouchers-Text([byte[]]$raw, [datetime]$from, [datetime]$to) {
    $t = [System.Text.Encoding]::UTF8.GetString($raw)
    $r = [pscustomobject]@{ Ok = $true; In = 0; Out = 0; Entries = ($t -match 'LEDGERENTRIES\.LIST') }
    $f = $from.ToString("yyyy-MM-dd"); $e = $to.ToString("yyyy-MM-dd")
    foreach ($m in [regex]::Matches($t, '<VOUCHER(?=[ >])(?![^<]*</VOUCHER>)[\s\S]*?<DATE[^>]*>([^<]+)</DATE>')) {
        $d = Iso-Date $m.Groups[1].Value
        if ($d -and $d -ge $f -and $d -le $e) { $r.In++ } else { $r.Out++ }
    }
    return $r
}

function Iso-Date([string]$s) {
    $s = $s.Trim()
    if ($s -match '^\d{8}$') { return $s.Substring(0,4) + "-" + $s.Substring(4,2) + "-" + $s.Substring(6,2) }
    $fmts = [string[]]@("d-MMM-yyyy", "d-MMM-yy", "dd-MMM-yyyy", "dd-MMM-yy")
    $d = [datetime]::MinValue
    if ([datetime]::TryParseExact($s, $fmts, [System.Globalization.CultureInfo]::InvariantCulture, 0, [ref]$d)) { return $d.ToString("yyyy-MM-dd") }
    return ""
}

# Checks a voucher response: how many vouchers fall inside [from, to], how many outside, and whether entries came along
function Check-Vouchers([byte[]]$raw, [datetime]$from, [datetime]$to) {
    $x = Parse-Xml $raw
    $r = [pscustomobject]@{ Ok = $false; In = 0; Out = 0; Entries = $false }
    if (-not $x) { return (Count-Vouchers-Text $raw $from $to) }
    $f = $from.ToString("yyyy-MM-dd"); $t = $to.ToString("yyyy-MM-dd")
    # only real vouchers: newer TallyPrime puts a <VOUCHER>count</VOUCHER> field in the company summary at the top
    foreach ($v in $x.SelectNodes("//VOUCHER[DATE]")) {
        $d = Iso-Date $v.SelectSingleNode("DATE").InnerText
        if ($d -and $d -ge $f -and $d -le $t) { $r.In++ } else { $r.Out++ }
    }
    $r.Entries = [bool]($x.SelectSingleNode("//ALLLEDGERENTRIES.LIST|//LEDGERENTRIES.LIST"))
    $r.Ok = $true
    return $r
}

# The server explains every failure in its reply; show that text instead of just "(500)"
function Error-Detail($err) {
    $detail = $err.Exception.Message
    $e = $err.Exception
    while ($e) {
        if ($e -is [System.Net.WebException] -and $e.Response) {
            try {
                $sr = New-Object System.IO.StreamReader($e.Response.GetResponseStream())
                $body = $sr.ReadToEnd()
                try { $j = $body | ConvertFrom-Json; if ($j.error) { $body = $j.error } } catch {}
                if ($body) { return ("server says: " + $body) }
            } catch {}
        }
        $e = $e.InnerException
    }
    return $detail
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
    $raw = Tally-Raw (Collection-Xml "TMCompanies" "Company" "Name, AltVchId, AltMstId, BooksFrom" "")
    $text = [System.Text.Encoding]::UTF8.GetString($raw)
    $eval = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) if ([int]$m.Groups[1].Value -lt 32) { "" } else { $m.Value } }
    $text = [regex]::Replace($text, '&#([0-9]+);', $eval)
    $text = [regex]::Replace($text, '[\x00-\x08\x0B\x0C\x0E-\x1F]', '')
    [xml]$x = $text
    $list = @()
    foreach ($n in $x.SelectNodes("//COMPANY")) {
        $name = $n.GetAttribute("NAME")
        if (-not $name) { $nn = $n.SelectSingleNode("NAME"); if ($nn) { $name = $nn.InnerText } }
        $av = $n.SelectSingleNode("ALTVCHID"); $am = $n.SelectSingleNode("ALTMSTID"); $bf = $n.SelectSingleNode("BOOKSFROM")
        $books = $null
        if ($bf) { try { $books = [datetime]::ParseExact($bf.InnerText.Trim(), "yyyyMMdd", $null) } catch {} }
        if ($name) {
            $list += [pscustomobject]@{
                Name = $name.Trim()
                BooksFrom = $books
                AltVch = $(if ($av) { $av.InnerText.Trim() } else { "" })
                AltMst = $(if ($am) { $am.InnerText.Trim() } else { "" })
            }
        }
    }
    return $list
}

# ------------------------------------------------------------------ main
try { $companies = @(Read-Companies) }
catch { Log ("Tally is not reachable on $Tally - is TallyPrime open? (" + $_.Exception.Message + ")") "Yellow"; End-Run 3 }

if ($companies.Count -eq 0) { Log "Tally is open but no company is loaded." "Yellow"; End-Run 3 }

# Which companies to sync, and from when (the Bahi Sync app's Companies list). A company not in the list is
# synced from the general start date, as before. Every company seen open in Tally is remembered for that list.
$CoCfg = @{}; $GlobalFrom = $FromDate
try { if ($Cfg.Companies) { foreach ($p in $Cfg.Companies.PSObject.Properties) { $CoCfg[$p.Name] = $p.Value } } } catch {}
function Company-Wanted($co) { $c = $CoCfg[$co.Name]; return -not ($c -and $c.PSObject.Properties["Sync"] -and $c.Sync -eq $false) }
function Company-From($co) {
    $c = $CoCfg[$co.Name]
    if ($c -and $c.PSObject.Properties["From"] -and $c.From) { try { return [datetime]::ParseExact([string]$c.From, "yyyy-MM-dd", $null) } catch {} }
    return $GlobalFrom
}
$SeenPath = Join-Path $Here "TallySync.companies.json"
try {
    $seen = @{}
    if (Test-Path $SeenPath) { foreach ($e in @((Get-Content $SeenPath -Raw | ConvertFrom-Json))) { if ($e.Name) { $seen[$e.Name] = $e } } }
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm")
    foreach ($co in $companies) {
        $seen[$co.Name] = [pscustomobject]@{ Name = $co.Name; BooksFrom = $(if ($co.BooksFrom) { $co.BooksFrom.ToString("yyyy-MM-dd") } else { "" }); LastOpen = $stamp }
    }
    ConvertTo-Json @($seen.Values | Sort-Object Name) | Set-Content $SeenPath -Encoding UTF8
} catch {}
$off = @($companies | Where-Object { -not (Company-Wanted $_) })
$companies = @($companies | Where-Object { Company-Wanted $_ })
if ($off.Count -and ($Force -or $Verbose -or $Now)) { Log ("Not syncing (switched off in Bahi Sync, Companies): " + (($off | ForEach-Object { $_.Name }) -join ", ")) }
if ($companies.Count -eq 0) { Log "None of the companies open in Tally is set to sync (Bahi Sync, Companies)." "Yellow"; End-Run 0 }

function Send-Heartbeat {
    try { [void](Server-Json "POST" "/agent/heartbeat" @{ companies = @($companies | ForEach-Object { $_.Name }); agent = $AgentVersion }) } catch {}
}

# The scheduled task runs every 2 minutes; the app decides whether it is time to sync
# (Settings: automatic every N minutes, manual "Sync now" only, or paused).
function Update-Task {
    $marker = Join-Path $Here "TallySync.task2"
    if (Test-Path $marker) { return }
    try {
        & schtasks.exe /Query /TN "Tally Mobile Sync" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return }
        $vbs = Join-Path $Here "run-hidden.vbs"
        & schtasks.exe /Create /TN "Tally Mobile Sync" /TR "wscript.exe `"$vbs`"" /SC MINUTE /MO 2 /F 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Set-Content $marker "2"; Log "The app now decides when to sync (Settings in the app). This PC checks every 2 minutes." }
    } catch {}
}
Update-Task
try {
    $sched = Server-Json "GET" ("/agent/schedule?force=" + $(if ($Force -or $Now) { "1" } else { "0" })) $null
    if (-not $sched.run) {
        Send-Heartbeat
        if ($sched.why -eq "paused" -and ($Force -or $Verbose)) { Log "Syncing is paused in the app (Reports, Settings). Nothing was sent." "Yellow" }
        elseif ($Verbose) { Log ("Not syncing now (" + $sched.why + ")") }
        End-Run 0
    }
    if ($sched.why -eq "asked") { $script:Asked = $true; Log "Sync asked for in the app - checking Tally for changes ..." }
    elseif ($Now) { $script:Asked = $true; Log "Sync asked for on this PC - checking Tally for changes ..." }
} catch {
    # an older server without sync settings: carry on as before
}

$BaseFrom = $FromDate
$exitCode = 0
$MethodFile = Join-Path $Here "TallySync.method"
$script:VchMethod = "daybook"
try { if ((Test-Path $MethodFile) -and ((Get-Content $MethodFile -Raw).Trim() -eq "collection")) { $script:VchMethod = "collection" } } catch {}

# Entries made on the phone that are already in Tally (guards against adding one twice)
$SentPath = Join-Path $Here "TallySync.sent"
$Sent = @{}
try { if (Test-Path $SentPath) { foreach ($l in (Get-Content $SentPath)) { if ($l.Trim()) { $Sent[$l.Trim()] = 1 } } } } catch {}

function Push-Entries($co) {
    # Receipts, payments and orders made on the phone: put them into this company in Tally
    $made = 0
    try { $ob = Server-Json "GET" ("/agent/outbox?company=" + [uri]::EscapeDataString($co.Name)) $null }
    catch {
        if ($_.Exception.Message -notmatch "\(404\)") { Log ("Could not check for phone entries: " + (Error-Detail $_)) "Yellow" }
        return 0
    }
    foreach ($e in @($ob.entries)) {
        if (-not $e) { continue }
        $res = @{ id = $e.id; ok = $false; error = ""; retry = $false }
        if ($Sent.ContainsKey([string]$e.uid)) {
            $res.ok = $true
        } else {
            try {
                $txt = [System.Text.Encoding]::UTF8.GetString((Tally-Raw $e.xml))
                $created = [regex]::Match($txt, '<CREATED>\s*(\d+)').Groups[1].Value
                $errs = @([regex]::Matches($txt, '<LINEERROR>([\s\S]*?)</LINEERROR>') | ForEach-Object { $_.Groups[1].Value.Trim() })
                if ($created -and [int]$created -ge 1) {
                    Add-Content -Path $SentPath -Value $e.uid -Encoding UTF8
                    $Sent[[string]$e.uid] = 1
                    $res.ok = $true; $made++
                    Log ("Phone entry added to Tally: " + $e.label) "Green"
                } else {
                    $res.error = if ($errs.Count) { $errs -join "; " } else { "Tally did not accept it: " + $txt.Substring(0, [Math]::Min(300, $txt.Length)) }
                    Log ("Phone entry not accepted by Tally (" + $e.label + "): " + $res.error) "Yellow"
                }
            } catch {
                $res.error = "Could not reach Tally: " + $_.Exception.Message; $res.retry = $true
            }
        }
        try { [void](Server-Json "POST" "/agent/outbox/result" $res) } catch { Log ("Could not report a phone entry back: " + (Error-Detail $_)) "Yellow" }
    }
    return $made
}

foreach ($co in $companies) {
    try {
        $state = Server-Json "GET" ("/agent/state?company=" + [uri]::EscapeDataString($co.Name)) $null
        if ($state.paused) {
            # switched off in the app (Reports, Settings): send nothing for this company
            if ($Force -or $Verbose -or $script:Asked) { Log ("Syncing is paused in the app for " + $co.Name + " - nothing sent. Resume it in Reports, Settings.") "Yellow" }
            continue
        }
        $madeEntries = Push-Entries $co
        # "Delete older vouchers" in the app sets keep_from: don't send anything before it
        $BaseFrom = Company-From $co
        $FromDate = $BaseFrom
        if ($state.keep_from -and $state.keep_from -gt $BaseFrom.ToString("yyyy-MM-dd")) {
            $FromDate = [datetime]::ParseExact($state.keep_from, "yyyy-MM-dd", $null)
        }
        $fromIso = $FromDate.ToString("yyyy-MM-dd"); $toIso = $ToDate.ToString("yyyy-MM-dd")
        # Tally's company change counter says whether anything changed. "Sync now" doesn't trust it alone:
        # it always compares voucher by voucher, so entries are found even if the counter didn't move.
        $unchanged = ($madeEntries -eq 0) -and (-not $script:Asked) -and (-not $state.need_groups) -and (-not $state.need_stock) -and $co.AltVch -and $co.AltMst -and ($state.alt_vch -eq $co.AltVch) -and
                     ($state.alt_mst -eq $co.AltMst) -and ($state.from_date -eq $fromIso)
        # Some Tally setups don't move that counter for every entry, so even when it says "unchanged"
        # the vouchers are compared one by one every 30 minutes.
        $deepKey = "deep_" + ($co.Name -replace '[^A-Za-z0-9]', '_')
        $deepFile = Join-Path $Here "TallySync.deep"
        $deep = @{}
        try { if (Test-Path $deepFile) { (Get-Content $deepFile -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object { $deep[$_.Name] = $_.Value } } } catch {}
        $deepCheck = $false
        if ($unchanged -and -not $Force) {
            $last = 0; try { $last = [double]$deep[$deepKey] } catch {}
            $nowSec = [double](Get-Date -UFormat %s)
            if ($nowSec - $last -lt 1800) { continue }
            $deepCheck = $true
            $deep[$deepKey] = $nowSec
            try { $deep | ConvertTo-Json | Set-Content $deepFile } catch {}
        }
        $t0 = Get-Date
        $run = [guid]::NewGuid().ToString("N")

        # 1. A light list of every voucher (GUID, change counter, date): tells the server what changed
        $light = $null; $expected = $null
        try {
            $light = Tally-Raw (VchCollection-Xml $co.Name $FromDate $ToDate "Date, GUID, AlterID, IsCancelled, IsOptional")
            $lx = Parse-Xml $light
            $expected = @{}
            if ($lx) {
                foreach ($v in $lx.SelectNodes("//VOUCHER")) {
                    $dn = $v.SelectSingleNode("DATE")
                    $d = if ($dn) { Iso-Date $dn.InnerText } else { "" }
                    if ($d) { $k = $d.Substring(0, 7); $expected[$k] = 1 + [int]$expected[$k] }
                }
            } else {
                foreach ($mt in [regex]::Matches([System.Text.Encoding]::UTF8.GetString($light), '<VOUCHER(?=[ >])(?![^<]*</VOUCHER>)[\s\S]*?<DATE[^>]*>([^<]+)</DATE>')) {
                    $d = Iso-Date $mt.Groups[1].Value
                    if ($d) { $k = $d.Substring(0, 7); $expected[$k] = 1 + [int]$expected[$k] }
                }
            }
        } catch { $light = $null; $expected = $null }

        # Without Tally's list of vouchers nothing can be checked: try again at the next run rather than
        # sending months that can't be counted
        if (-not $light) {
            Log ("Tally didn't send its list of vouchers for " + $co.Name + " (busy?). Trying again at the next sync.") "Yellow"
            $exitCode = 1
            continue
        }

        # 2. Ask the server which months need resending
        $full = $true; $months = @(); $byVch = $false; $changed = @(); $deleted = @(); $since = ""
        if ($light -and -not $Force) {
            try {
                $wc = Server-Client
                $wc.Headers.Add("Content-Type", "application/octet-stream"); $wc.Headers.Add("X-Gzip", "1")
                $q = "company=" + [uri]::EscapeDataString($co.Name) + "&from=$fromIso&to=$toIso"
                $plan = [System.Text.Encoding]::UTF8.GetString($wc.UploadData("$Server/agent/plan?$q", "POST", (Gzip $light))) | ConvertFrom-Json
                $full = [bool]$plan.full
                $months = @($plan.months)
                $byVch = (-not $full) -and [bool]$plan.by_voucher
                $changed = @($plan.changed | Where-Object { $_ })
                $deleted = @($plan.deleted | Where-Object { $_ })
                $since = [string]$plan.since
            } catch {
                # the server didn't answer: don't fall back to a full resend of every month; try again next time
                Log ("The server didn't answer which months changed (" + $_.Exception.Message + "). Trying again at the next sync.") "Yellow"
                $exitCode = 1
                continue
            }
        }
        if ($deepCheck -and -not $full -and $months.Count -eq 0) { continue }   # the 30-minute check found nothing new
        if ($deepCheck) { Log ("Found changes in " + $co.Name + " that Tally's change counter didn't show.") }
        $mastersChanged = $full -or ($state.alt_mst -ne $co.AltMst) -or [bool]$state.need_groups
        if ($full) { Log ("Syncing " + $co.Name + " (" + $fromIso + " to " + $toIso + ") - full ...") "Cyan" }
        elseif ($byVch -and ($changed.Count + $deleted.Count)) { Log ("Syncing " + $co.Name + " - " + $changed.Count + " new or changed, " + $deleted.Count + " deleted voucher(s) ...") "Cyan" }
        else { Log ("Syncing " + $co.Name + " - " + $(if ($months.Count) { "changed months: " + ($months -join ", ") } else { "no voucher changes found, refreshing balances" }) + " ...") "Cyan" }

        # 3. Masters: ledgers and stock every time (their balances move with every entry), the rest only when changed
        if ($mastersChanged) {
            Send-Part $run "groups"  (Tally-Raw (Collection-Xml "TMGroups" "Group" "Name, Parent, IsRevenue, AffectsGrossProfit, IsDeemedPositive" $co.Name))
            Send-Part $run "vtypes"  (Tally-Raw (Collection-Xml "TMVchTypes" "VoucherType" "Name, Parent" $co.Name))
        }
        Send-Part $run "ledgers" (Tally-Raw (Collection-Xml "TMLedgers" "Ledger" `
            "Name, Parent, OpeningBalance, ClosingBalance, LedgerPhone, LedgerMobile, Email, PartyGSTIN, TaxType, GSTDutyHead" $co.Name))
        Send-Part $run "stock"   (Tally-Raw (Collection-Xml "TMStock" "StockItem" `
            "Name, Parent, BaseUnits, OpeningBalance, OpeningValue, ClosingBalance, ClosingValue, ClosingRate" $co.Name))
        # each item's opening stock by godown (separate, so a Tally that doesn't give it can't stop the sync)
        try { Send-Part $run "stock_godown" (Tally-Raw (Collection-Xml "TMStockGdn" "StockItem" "Name, BatchAllocations" $co.Name)) }
        catch { if ($Verbose) { Log ("Godown openings not read: " + $_.Exception.Message) "Gray" } }

        if ($mastersChanged) {
            # Details used for printing invoices and statements (optional - skipped if Tally refuses)
            $extras = @(
                @("company",  { Collection-Xml "TMCompanyInfo" "Company" "Name, Address, StateName, PinCode, Email, PhoneNumber, IncomeTaxNumber, GSTRegistrationNumber, CountryName, Website" $co.Name }),
                @("ledger_x", { Masters-Xml "Ledgers" $co.Name }),
                @("stock_x",  { Masters-Xml "Stock Items" $co.Name })
            )
            foreach ($x in $extras) {
                $data = $null
                try { $data = Tally-Raw (& $x[1]) }
                catch { Log ("Could not read " + $x[0] + " details from Tally: " + $_.Exception.Message) "Yellow" }
                if ($data) {
                    try { Send-Part $run $x[0] $data }
                    catch { Log ("The server refused " + $x[0] + " details - update the Bahi server to the latest version. (" + (Error-Detail $_) + ")") "Yellow" }
                }
            }
        }

        # Bill-wise outstanding as Tally calculates it (skipped quietly if this Tally can't export it)
        foreach ($r in @(@("bills_rec", "Bills Receivable"), @("bills_pay", "Bills Payable"))) {
            $data = $null
            try { $data = Tally-Raw (Report-Xml $r[1] $co.Name $FromDate $today.Date) }
            catch { Log ("Could not read " + $r[1] + " from Tally: " + $_.Exception.Message) "Yellow" }
            if ($data) {
                try { Send-Part $run $r[0] $data }
                catch { Log ("The server refused " + $r[1] + " - update the Bahi server to the latest version. (" + (Error-Detail $_) + ")") "Yellow" }
            }
        }

        # 4a. Only the vouchers that changed, fetched by GUID (25 at a time). If Tally sends back fewer than
        #     asked for, fall back to whole months below.
        $sentByVch = $false
        $noGuidFile = Join-Path $Here "TallySync.noguid"
        if ($byVch -and $changed.Count -gt 0 -and (Test-Path $noGuidFile)) { $byVch = $false }   # this Tally can't pick single vouchers
        if ($byVch -and $changed.Count -gt 0) {
            $parts = @(); $got = 0
            try {
                for ($i = 0; $i -lt $changed.Count; $i += 25) {
                    $batch = @($changed[$i..([math]::Min($i + 24, $changed.Count - 1))])
                    $raw = Tally-Raw (VchGuid-Xml $co.Name $batch $VchFields)
                    $c = Check-Vouchers $raw $FromDate $ToDate
                    $got += [math]::Max(0, $c.In); $parts += , $raw
                }
            } catch { $got = -1 }
            if ($got -eq $changed.Count) {
                foreach ($p in $parts) { Send-Part $run "daybook" $p }
                for ($i = 0; $i -lt $changed.Count; $i += 25) {
                    Send-Einv $run $co.Name $FromDate $ToDate @($changed[$i..([math]::Min($i + 24, $changed.Count - 1))])
                }
                Log ("Vouchers checked: all " + $changed.Count + " changed voucher(s) received")
                $sentByVch = $true
            } else {
                Log ("Fetching single vouchers didn't work here (" + $got + " of " + $changed.Count + ") - sending whole months instead, from now on") "Gray"
                if ($got -gt $changed.Count) { try { Set-Content $noGuidFile "1" } catch {} }
                $byVch = $false
            }
        } elseif ($byVch) { $sentByVch = $true }   # only deletions, or nothing at all

        # 4. Vouchers, one month at a time (all months on a full sync, only changed ones otherwise).
        # Day Book first; if Tally ignores the dates or sends too few, use a date-filtered voucher collection.
        $todo = @()
        $m = Get-Date -Year $FromDate.Year -Month $FromDate.Month -Day 1
        while ($m -le $ToDate) {
            if ($full -or ((-not $sentByVch) -and ($months -contains $m.ToString("yyyy-MM")))) { $todo += $m }
            $m = $m.AddMonths(1)
        }
        $method = $script:VchMethod; $sentTotal = 0; $expTotal = 0; $short = @(); $sentMonths = @(); $note = @()
        foreach ($m in $todo) {
            $mEnd = $m.AddMonths(1).AddDays(-1)
            $a = if ($m -lt $FromDate) { $FromDate } else { $m }
            $b = if ($mEnd -gt $ToDate) { $ToDate } else { $mEnd }
            $key = $m.ToString("yyyy-MM")
            $want = if ($expected) { [int]$expected[$key] } else { -1 }
            if ($want -gt 0) { $expTotal += $want }

            $best = $null; $bestIn = -1; $bestGood = $false; $why = ""
            # Once the Day Book is known to ignore dates (it then sends Tally's current day for every month, which
            # looks right for the current month), it is never used again. The collection is asked twice if busy.
            $ways = if ($method -eq "collection") { @("collection", "collection") } else { @("daybook", "collection") }
            foreach ($how in $ways) {
                try {
                    $raw = if ($how -eq "daybook") { Tally-Raw (DayBook-Xml $co.Name $a $b) } else { Tally-Raw (VchCollection-Xml $co.Name $a $b $VchFields) }
                } catch { Start-Sleep -Seconds 5; continue }
                $c = Check-Vouchers $raw $a $b
                # The Day Book must not send other days (that is how a Day Book ignoring dates shows); the
                # date-filtered collection may carry other bits, and the server keeps only this month's vouchers
                $outOk = ($how -ne "daybook") -or ($c.Out -eq 0)
                # the date-filtered collection is sent even when it has fewer vouchers than Tally listed: the server
                # compares voucher by voucher and keeps its copy of a month that would lose any it already has.
                # A Day Book answer must be complete (a short one is how a Day Book ignoring dates shows).
                $countOk = ($want -lt 0) -or ($c.In -ge $want) -or ($how -ne "daybook")
                $good = $c.Ok -and $outOk -and ($c.In -eq 0 -or $c.Entries) -and $countOk
                if ($good -and $want -ge 0 -and $c.In -lt $want) { $note += ("{0}: {1} of {2}" -f $key, $c.In, $want) }
                if (-not $good) { $why = "{0}: got {1}, outside the month {2}, entries {3}" -f $how, $c.In, $c.Out, $(if ($c.Entries) { "yes" } else { "no" }) }
                if ($c.Ok -and $c.Entries -and $c.In -gt $bestIn) { $best = $raw; $bestIn = $c.In }
                if ($good) {
                    $bestGood = $true
                    $best = $raw; $bestIn = $c.In
                    if ($how -ne $method) {
                        if ($how -eq "collection") { Log ("This Tally's Day Book export ignores dates - using the voucher collection method instead") "Gray" }
                        $method = $how
                    }
                    break
                }
            }
            # only a complete month is sent: a short or failed month keeps what the server already has
            if ($best -and $bestGood) { Send-Part $run "daybook" $best; $sentTotal += [math]::Max(0, $bestIn); Send-Einv $run $co.Name $a $b $null; $sentMonths += $key }
            else { $short += ("{0}: {1} of {2}{3}" -f $key, [math]::Max(0, $bestIn), $want, $(if ($why) { " (" + $why + ")" } else { "" })) }
        }
        if ($method -ne $script:VchMethod) { try { Set-Content $MethodFile $method } catch {} }
        $script:VchMethod = $method
        if ($expected -and $todo.Count -and $short.Count -eq 0 -and $note.Count -eq 0) { Log ("Vouchers checked: all $expTotal vouchers in the " + $todo.Count + " month(s) sent were received") }
        if ($note.Count -gt 0) { Log ("Tally sent fewer vouchers than it listed for " + ($note -join "; ") + " - the server keeps any it already has.") "Yellow" }
        if ($short.Count -gt 0) {
            Log ("Some months didn't come back complete from Tally and were not sent (the app keeps what it had): " + ($short -join "; ") + ". They are tried again at the next sync.") "Yellow"
            $exitCode = 1
            if ($full) { continue }       # a full sync replaces everything, so it must not go ahead with a gap
        }

        # e-way bills and e-invoices made after an invoice was synced don't always move Tally's change counter,
        # so the last 15 days' details are read every time (only those fields; the server adds them to its copy)
        $eFrom = $today.Date.AddDays(-15); if ($eFrom -lt $FromDate) { $eFrom = $FromDate }
        if ($eFrom -le $ToDate) { Send-Einv $run $co.Name $eFrom $ToDate $null }

        # 5. Stock as Tally has it at each month-end, so opening stock for any month or year is Tally's own figure.
        #    All months on a full sync; otherwise only from the month of the earliest change.
        $snapFrom = $null
        if ($full -or $mastersChanged -or $state.need_stock -or $state.need_ledgers) { $snapFrom = $FromDate.AddDays(-1) }
        elseif ($since) { try { $snapFrom = [datetime]::ParseExact($since, "yyyy-MM-dd", $null) } catch {} }
        if ($snapFrom) {
            $days = @()
            $d = (Get-Date -Year $snapFrom.Year -Month $snapFrom.Month -Day 1).AddMonths(1).AddDays(-1)   # end of that month
            if ($snapFrom -eq $FromDate.AddDays(-1)) { $days += $snapFrom }
            while ($d -lt $today.Date -and $d -le $ToDate) { if ($days -notcontains $d) { $days += $d }; $d = $d.AddDays(1).AddMonths(1).AddDays(-1) }
            # the books' beginning; if this Tally doesn't say, the sync start (and no figure for the day before it)
            $books = if ($co.BooksFrom) { $co.BooksFrom } else { $BaseFrom }
            $snapOk = 0
            foreach ($day in $days) {
                if ($day -lt $books -and -not $co.BooksFrom) { continue }
                $q = "&date=" + $day.ToString("yyyy-MM-dd") + $(if ($day -lt $books) { "&opening=1" } else { "" })
                try {
                    $raw = Tally-Raw (BalanceAt-Xml $co.Name "StockItem" $books $day)
                    $wc = Server-Client
                    $wc.Headers.Add("Content-Type", "application/octet-stream"); $wc.Headers.Add("X-Gzip", "1")
                    [void]$wc.UploadData("$Server/agent/part?run=$run&kind=stockat$q", "POST", (Gzip $raw))
                    $snapOk++
                } catch { Log ("Could not read stock as at " + $day.ToString("d-MMM-yyyy") + ": " + (Error-Detail $_)) "Yellow"; break }
                # each ledger's balance on the same day: lets the app check it has every entry Tally has
                try {
                    $raw = Tally-Raw (BalanceAt-Xml $co.Name "Ledger" $books $day)
                    $wc = Server-Client
                    $wc.Headers.Add("Content-Type", "application/octet-stream"); $wc.Headers.Add("X-Gzip", "1")
                    [void]$wc.UploadData("$Server/agent/part?run=$run&kind=ledgerat$q", "POST", (Gzip $raw))
                } catch { if ($Verbose) { Log ("Ledger balances as at " + $day.ToString("d-MMM-yyyy") + " not read: " + $_.Exception.Message) "Gray" } }
            }
            if ($snapOk -and $Verbose) { Log ("Stock read at $snapOk month-end(s)") }
        }

        $meta = @{ run = $run; company = $co.Name; from = $fromIso; to = $toIso; alt_vch = $co.AltVch; alt_mst = $co.AltMst }
        if ($sentByVch) { $meta.guids = @($changed + $deleted) }
        elseif (-not $full) { $meta.months = @($sentMonths) }
        if ($short.Count -gt 0) { $meta.alt_vch = "" }      # not complete: the next run looks again
        $res = Server-Json "POST" "/agent/commit" $meta
        if ($res.held) { Log ("The server kept its own copy of " + $res.held + " (vouchers it has were missing) - tried again at the next sync.") "Yellow" }
        $secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        Log ("Done: " + $res.ledgers + " ledgers, " + $res.stock + " stock items, " + $res.vouchers +
             " vouchers in $secs s") "Green"
        if ($res.unbalanced -gt 0) { Log ("Note: " + $res.unbalanced + " vouchers did not balance - see Reports, Sync check in the app") "Yellow" }
    } catch {
        $exitCode = 1
        Log ("Sync failed for " + $co.Name + ": " + (Error-Detail $_)) "Red"
    }
}

Send-Heartbeat
if ($script:Asked) { Log ("Sync finished for " + $companies.Count + " compan" + $(if ($companies.Count -eq 1) { "y" } else { "ies" }) + " open in Tally.") }
End-Run $exitCode
