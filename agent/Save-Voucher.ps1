# Save-Voucher.ps1 - saves everything Tally has for ONE voucher into a file, so its e-invoice and
# e-way bill fields can be checked. Only talks to Tally on this PC; nothing is sent anywhere.
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tally = "http://localhost:9000"
try { $cfg = Get-Content (Join-Path $Here "TallySync.config.json") -Raw | ConvertFrom-Json; if ($cfg.TallyUrl) { $Tally = $cfg.TallyUrl } } catch {}

function Tally-Text([string]$xml) {
    # read only: this tool never changes anything in Tally
    if ($xml -notmatch '<TALLYREQUEST>Export</TALLYREQUEST>' -or $xml -match '(?i)ACTION\s*=|<ACTION[\s>]|IMPORT|<DELETE|<ALTER|<CANCEL') { throw "Blocked: not a read request" }
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add("Content-Type", "text/xml;charset=utf-8")
    return [System.Text.Encoding]::UTF8.GetString($wc.UploadData($Tally, "POST", [System.Text.Encoding]::UTF8.GetBytes($xml)))
}
function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }

Write-Host "Save one voucher from Tally (for checking e-invoice / e-way bill details)" -ForegroundColor Cyan
Write-Host "Keep TallyPrime open with the company loaded."
$no = (Read-Host "Voucher number exactly as in Tally (e.g. 2026-27/GST/1317)").Trim()
if (-not $no) { exit 1 }
$co = (Read-Host "Company name (press Enter for the company open in Tally)").Trim()
$sv = "<SVEXPORTFORMAT>`$`$SysName:XML</SVEXPORTFORMAT><SVFROMDATE TYPE=`"Date`">1-Apr-2000</SVFROMDATE><SVTODATE TYPE=`"Date`">31-Mar-2100</SVTODATE>"
if ($co) { $sv += "<SVCURRENTCOMPANY>" + (Esc $co) + "</SVCURRENTCOMPANY>" }
$filter = "<SYSTEM TYPE=`"Formulae`" NAME=`"TMOne`">`$VoucherNumber = `"" + (Esc $no) + "`"</SYSTEM>"
$all = "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE><ID>TMOneVch</ID></HEADER>" +
       "<BODY><DESC><STATICVARIABLES>$sv</STATICVARIABLES><TDL><TDLMESSAGE>" +
       "<COLLECTION NAME=`"TMOneVch`" ISMODIFY=`"No`"><TYPE>Voucher</TYPE><NATIVEMETHOD>*</NATIVEMETHOD><FILTER>TMOne</FILTER></COLLECTION>" +
       $filter + "</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"
$ein = $all.Replace("<NATIVEMETHOD>*</NATIVEMETHOD>", "<FETCH>GUID, VoucherNumber, IRN, IRNAckNo, IRNAckDate, IRNQRCode, EWayBillDetails</FETCH>")
$out = Join-Path $Here "voucher-sample.xml"
$parts = @()
foreach ($pair in @(@("all fields", $all), @("e-invoice fields", $ein))) {
    try { $parts += "<!-- " + $pair[0] + " -->`r`n" + (Tally-Text $pair[1]) }
    catch { $parts += "<!-- " + $pair[0] + ": " + $_.Exception.Message + " -->" }
}
Set-Content -Path $out -Value ($parts -join "`r`n`r`n") -Encoding UTF8
$size = (Get-Item $out).Length
if ((Get-Content $out -Raw) -match [regex]::Escape($no)) {
    Write-Host "Saved $out ($size bytes)." -ForegroundColor Green
    Write-Host "Attach this file in the chat with Claude. It holds this one invoice's details (party, items, amounts)."
} else {
    Write-Host "Saved $out, but the voucher $no wasn't found in it. Check the number and that the right company is open." -ForegroundColor Yellow
}
