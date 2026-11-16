# Base Sepolia 治理状态验证：2-of-3 多签 + 1h 延迟
# 用法：powershell -File scripts/ops/verify-base-sepolia-governance.ps1
$ErrorActionPreference = "Stop"
$cast = "C:\Users\Administrator\.foundry\bin\cast.exe"
$rpc = "https://sepolia.base.org"
$tl  = "0x57bB003B06812F0C65390f0326EAF7260E20F4CC"

$expected = @{
    ownerCount = "3"
    threshold  = "2"
    minDelay   = "3600"
    owners = @(
        "0x79BFfa6fF14B0b0e6766AB6A29d210f56E76336e",
        "0x47D782e14E444AADD806912b1119516C95E89e7c",
        "0x9DE93aD8eBc00484E110652c9E35Cb302aad579b"
    )
}

function Invoke-Call([string]$sig, [string[]]$callArgs) {
    $out = & $cast call $tl $sig @callArgs --rpc-url $rpc 2>&1
    return ($out -join "").Trim()
}

$ok = $true
$ownerCount = Invoke-Call "ownerCount()(uint256)" @()
"ownerCount = $ownerCount"
if ($ownerCount -ne $expected.ownerCount) { $ok = $false }

$threshold = Invoke-Call "threshold()(uint256)" @()
"threshold  = $threshold"
if ($threshold -ne $expected.threshold) { $ok = $false }

$minDelay = Invoke-Call "minDelay()(uint256)" @()
"minDelay   = $minDelay"
if ($minDelay -ne $expected.minDelay) { $ok = $false }

for ($i = 0; $i -lt $expected.owners.Count; $i++) {
    $o = Invoke-Call "owners(uint256)(address)" @($i)
    "owners[$i]  = $o"
    if ($o.ToLower() -ne $expected.owners[$i].ToLower()) { $ok = $false }
}

if ($ok) {
    "`nOK: Base Sepolia governance hardened (2-of-3 + 3600s delay)"
    exit 0
} else {
    "`nFAIL: governance state mismatch"
    exit 1
}
