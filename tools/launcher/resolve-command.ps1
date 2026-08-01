[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Name
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-PortableComponent {
    param([string]$Value)

    if (
        [string]::IsNullOrWhiteSpace($Value) -or
        $Value -in @(".", "..") -or
        $Value.Trim() -cne $Value -or
        $Value.EndsWith(" ") -or
        $Value.EndsWith(".") -or
        [Text.Encoding]::UTF8.GetByteCount($Value) -gt 255
    ) {
        return $false
    }
    foreach ($character in $Value.ToCharArray()) {
        $codePoint = [int][char]$character
        if (
            $codePoint -le 31 -or
            $codePoint -eq 127 -or
            ($codePoint -ge 0xD800 -and $codePoint -le 0xDFFF) -or
            '<>:"/\|?*'.IndexOf($character) -ge 0
        ) {
            return $false
        }
    }
    $stem = $Value.Split(".")[0].ToUpperInvariant()
    if ($stem -match '\A(CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])\z') {
        return $false
    }
    return $true
}

function Test-ExactAbsolutePath {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Trim() -cne $Value) {
        return $false
    }
    if ($Value.ToCharArray() | Where-Object { [char]::IsControl($_) }) {
        return $false
    }
    $driveAbsolute = $Value -match "^[A-Za-z]:[\\/]"
    $uncAbsolute = $Value -match "^[\\/]{2}[^\\/]+[\\/][^\\/]+"
    if (-not ($driveAbsolute -or $uncAbsolute)) {
        return $false
    }
    $portable = $Value.Replace("\", "/")
    if ($portable.StartsWith("//?/") -or $portable.StartsWith("//./") -or $portable.StartsWith("/??/")) {
        return $false
    }
    if ($driveAbsolute) {
        $tail = $portable.Substring(3)
        $components = if ($tail.Length -eq 0) {
            @()
        }
        else {
            @($tail.Split("/"))
        }
    }
    else {
        $components = @($portable.Substring(2).Split("/"))
        if ($components.Count -lt 2) {
            return $false
        }
        if ($components.Count -eq 3 -and $components[2].Length -eq 0) {
            $components = @($components[0], $components[1])
        }
    }
    foreach ($component in $components) {
        if (-not (Test-PortableComponent $component)) {
            return $false
        }
    }
    return $true
}

function Test-NoReparseComponents {
    param([System.IO.FileSystemInfo]$Item)

    $cursor = $Item
    while ($null -ne $cursor) {
        if (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            return $false
        }
        $cursor = $cursor.Parent
    }
    return $true
}

if (-not (Test-PortableComponent $Name)) {
    exit 1
}

$extensions = if ([IO.Path]::GetExtension($Name)) {
    @("")
}
else {
    $configured = if ([string]::IsNullOrWhiteSpace($env:PATHEXT)) {
        ".COM;.EXE;.BAT;.CMD"
    }
    else {
        $env:PATHEXT
    }
    @(
        $configured.Split(";") |
            Where-Object { $_ -match "\A\.[A-Za-z0-9]+\z" } |
            Select-Object -Unique
    )
}

foreach ($rawDirectory in $env:PATH.Split(";")) {
    if (-not (Test-ExactAbsolutePath $rawDirectory)) {
        continue
    }
    foreach ($extension in $extensions) {
        $candidateName = "$Name$extension"
        if (-not (Test-PortableComponent $candidateName)) {
            continue
        }
        $candidate = Join-Path -Path $rawDirectory -ChildPath $candidateName
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $item = Get-Item -LiteralPath $candidate -Force
        if (-not (Test-NoReparseComponents $item)) {
            continue
        }
        [Console]::Out.WriteLine($item.FullName)
        exit 0
    }
}

exit 1
