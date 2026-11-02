[CmdletBinding()]
param(
  [string]$NsisInstallerPath = "",
  [string]$LegacyMsiPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$LegacyMsiUrl = "https://github.com/RachelForster/Shinsekai/releases/download/v2.1.0/Shinsekai-2.1.0_windows-x64.msi"
$LegacyMsiSha256 = "c896cc45f718a41f9e2183d624e8af60c998718a3842ed2686f745f93b6cdce9"
$LegacyVersion = "2.1.0"
$ProductName = "Shinsekai"
$MigrationRegistryPath = "Registry::HKEY_CURRENT_USER\Software\studio.shinsekai\Migration"
$MigrationRegistryValue = "LegacyMsiAppRoot"
$LegacyProductRegistryPath = "Registry::HKEY_CURRENT_USER\Software\shinsekai\Shinsekai"
$NsisUninstallRegistryPath = "Registry::HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall\Shinsekai"
$StudioRegistryParentPath = "Registry::HKEY_CURRENT_USER\Software\studio.shinsekai"
$LegacyRegistryParentPath = "Registry::HKEY_CURRENT_USER\Software\shinsekai"

$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$FrontendRoot = Join-Path $RepositoryRoot "frontend"
if ([string]::IsNullOrWhiteSpace($LegacyMsiPath)) {
  $LegacyMsiPath = Join-Path $RepositoryRoot ".cache\legacy-installers\Shinsekai-2.1.0_windows-x64.msi"
} elseif (-not [IO.Path]::IsPathRooted($LegacyMsiPath)) {
  $LegacyMsiPath = Join-Path $RepositoryRoot $LegacyMsiPath
}
$LegacyMsiPath = [IO.Path]::GetFullPath($LegacyMsiPath)
$CurrentVersion = (Get-Content -LiteralPath (Join-Path $FrontendRoot "package.json") -Raw | ConvertFrom-Json).version
$ProgramFiles64 = [Environment]::GetFolderPath("ProgramFiles")
$LocalAppData = [Environment]::GetFolderPath("LocalApplicationData")
$ExpectedLegacyInstallDir = Join-Path $ProgramFiles64 $ProductName
$ExpectedNsisInstallDir = Join-Path $LocalAppData $ProductName
$RunnerTemp = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
  [IO.Path]::GetTempPath()
} else {
  $env:RUNNER_TEMP
}
$TestRoot = Join-Path $RunnerTemp ("shinsekai-msi-nsis-migration-" + [Guid]::NewGuid().ToString("N"))
$MsiInstallLog = Join-Path $TestRoot "msi-install.log"
$MsiCleanupLog = Join-Path $TestRoot "msi-cleanup.log"
$SeedToken = "shinsekai-msi-migration-" + [Guid]::NewGuid().ToString("N")
$SeedFile = Join-Path $ExpectedLegacyInstallDir "data\config\system_config.yaml"
$LegacyProductCode = ""
$TestFailure = $null
$CleanupErrors = [Collections.Generic.List[string]]::new()
$CleanupAuthorized = $false
$StudioRegistryParentExisted = $false
$LegacyRegistryParentExisted = $false

function Write-Step {
  param([Parameter(Mandatory)][string]$Message)
  Write-Host "[msi-to-nsis] $Message"
}

function Assert-Condition {
  param(
    [Parameter(Mandatory)][bool]$Condition,
    [Parameter(Mandatory)][string]$Message
  )
  if (-not $Condition) {
    throw "Assertion failed: $Message"
  }
}

function Ensure-LegacyMsiFixture {
  param(
    [Parameter(Mandatory)][string]$Uri,
    [Parameter(Mandatory)][string]$DestinationPath,
    [Parameter(Mandatory)][string]$ExpectedSha256,
    [ValidateRange(1, 10)][int]$MaxAttempts = 5,
    [ValidateRange(60, 900)][int]$TotalTimeoutSeconds = 360
  )

  $destinationDirectory = Split-Path -Parent $DestinationPath
  New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null

  if (Test-Path -LiteralPath $DestinationPath -PathType Leaf) {
    $cachedHash = (Get-FileHash -LiteralPath $DestinationPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($cachedHash -ceq $ExpectedSha256) {
      Write-Step "Using the verified cached v2.1.0 x64 MSI"
      return $false
    }

    Write-Warning "Ignoring legacy MSI cache with SHA-256 $cachedHash; expected $ExpectedSha256"
    Remove-Item -LiteralPath $DestinationPath -Force
  }

  $lastFailure = "total download time budget was exhausted"
  $partialPath = "$DestinationPath.partial.$PID"
  $downloadClock = [Diagnostics.Stopwatch]::StartNew()
  try {
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt += 1) {
      if (Test-Path -LiteralPath $partialPath) {
        Remove-Item -LiteralPath $partialPath -Force
      }
      $remainingSeconds = $TotalTimeoutSeconds - [int][Math]::Ceiling($downloadClock.Elapsed.TotalSeconds)
      if ($remainingSeconds -le 0) {
        break
      }
      $requestTimeoutSeconds = [int][Math]::Min(60, $remainingSeconds)

      Write-Step "Downloading the pinned v2.1.0 x64 MSI (attempt $attempt/$MaxAttempts)"
      try {
        $httpClient = [Net.Http.HttpClient]::new()
        try {
          $httpClient.Timeout = [TimeSpan]::FromSeconds($requestTimeoutSeconds)
          $downloadBytes = $httpClient.GetByteArrayAsync($Uri).GetAwaiter().GetResult()
          [IO.File]::WriteAllBytes($partialPath, $downloadBytes)
          $downloadBytes = $null
        } finally {
          $httpClient.Dispose()
        }

        $downloadHash = (Get-FileHash -LiteralPath $partialPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($downloadHash -cne $ExpectedSha256) {
          throw "legacy MSI SHA-256 mismatch: expected $ExpectedSha256, got $downloadHash"
        }

        Move-Item -LiteralPath $partialPath -Destination $DestinationPath -Force
        Write-Step "Cached the verified v2.1.0 x64 MSI"
        return $true
      } catch {
        $lastFailure = $_.Exception.Message
        if (Test-Path -LiteralPath $partialPath) {
          Remove-Item -LiteralPath $partialPath -Force
        }
        $remainingSeconds = $TotalTimeoutSeconds - [int][Math]::Ceiling($downloadClock.Elapsed.TotalSeconds)
        if ($attempt -lt $MaxAttempts -and $remainingSeconds -gt 0) {
          $retryDelaySeconds = [int][Math]::Min([Math]::Pow(2, $attempt), $remainingSeconds)
          Write-Warning "Legacy MSI download attempt $attempt failed: $lastFailure. Retrying in $retryDelaySeconds second(s)."
          Start-Sleep -Seconds $retryDelaySeconds
        }
      }
    }
  } finally {
    $downloadClock.Stop()
    if (Test-Path -LiteralPath $partialPath) {
      Remove-Item -LiteralPath $partialPath -Force
    }
  }

  throw "Unable to download and verify the legacy MSI after $MaxAttempts attempts within a $TotalTimeoutSeconds-second retry budget. Last failure: $lastFailure"
}

function Test-StringEqual {
  param(
    [AllowEmptyString()][string]$Left,
    [AllowEmptyString()][string]$Right
  )
  return [string]::Equals($Left, $Right, [StringComparison]::OrdinalIgnoreCase)
}

function Normalize-InstallPath {
  param([AllowNull()][AllowEmptyString()][string]$Path)
  if ([string]::IsNullOrWhiteSpace($Path)) {
    return ""
  }
  $trimmed = $Path.Trim().Trim('"')
  return [IO.Path]::GetFullPath($trimmed).TrimEnd('\')
}

function Get-RegistryValue {
  param(
    [Parameter(Mandatory)][Microsoft.Win32.RegistryKey]$Key,
    [Parameter(Mandatory)][AllowEmptyString()][string]$Name
  )
  return $Key.GetValue(
    $Name,
    $null,
    [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
  )
}

function Get-UninstallEntries {
  $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
  $locations = @(
    @{
      Hive = [Microsoft.Win32.RegistryHive]::LocalMachine
      HiveName = "HKLM"
    },
    @{
      Hive = [Microsoft.Win32.RegistryHive]::CurrentUser
      HiveName = "HKCU"
    }
  )
  $views = @(
    [Microsoft.Win32.RegistryView]::Registry64,
    [Microsoft.Win32.RegistryView]::Registry32
  )

  foreach ($location in $locations) {
    foreach ($view in $views) {
      $baseKey = $null
      $uninstallKey = $null
      try {
        $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey($location.Hive, $view)
        $uninstallKey = $baseKey.OpenSubKey("Software\Microsoft\Windows\CurrentVersion\Uninstall")
        if ($null -eq $uninstallKey) {
          continue
        }
        foreach ($keyName in $uninstallKey.GetSubKeyNames()) {
          $entryKey = $null
          try {
            $entryKey = $uninstallKey.OpenSubKey($keyName)
            if ($null -eq $entryKey) {
              continue
            }
            $displayName = Get-RegistryValue -Key $entryKey -Name "DisplayName"
            if ([string]::IsNullOrWhiteSpace([string]$displayName)) {
              continue
            }
            $uninstallString = [string](Get-RegistryValue -Key $entryKey -Name "UninstallString")
            $installLocation = [string](Get-RegistryValue -Key $entryKey -Name "InstallLocation")
            $identity = "{0}|{1}|{2}|{3}|{4}" -f @(
              $location.HiveName,
              $keyName,
              $displayName,
              $uninstallString,
              $installLocation
            )
            if (-not $seen.Add($identity)) {
              continue
            }
            [PSCustomObject]@{
              HiveName = $location.HiveName
              View = $view.ToString()
              KeyName = $keyName
              DisplayName = [string]$displayName
              DisplayVersion = [string](Get-RegistryValue -Key $entryKey -Name "DisplayVersion")
              Publisher = [string](Get-RegistryValue -Key $entryKey -Name "Publisher")
              InstallLocation = $installLocation
              UninstallString = $uninstallString
              WindowsInstaller = Get-RegistryValue -Key $entryKey -Name "WindowsInstaller"
            }
          } finally {
            if ($null -ne $entryKey) {
              $entryKey.Dispose()
            }
          }
        }
      } finally {
        if ($null -ne $uninstallKey) {
          $uninstallKey.Dispose()
        }
        if ($null -ne $baseKey) {
          $baseKey.Dispose()
        }
      }
    }
  }
}

function Get-ShinsekaiEntries {
  return @(
    Get-UninstallEntries | Where-Object {
      Test-StringEqual -Left $_.DisplayName -Right $ProductName
    }
  )
}

function Test-MsiEntry {
  param([Parameter(Mandatory)]$Entry)
  return ($Entry.WindowsInstaller -eq 1) -or ($Entry.UninstallString -match "(?i)msiexec(?:\.exe)?")
}

function Invoke-CheckedProcess {
  param(
    [Parameter(Mandatory)][string]$FilePath,
    [Parameter(Mandatory)][string[]]$ArgumentList,
    [int[]]$AllowedExitCodes = @(0),
    [int]$TimeoutSeconds = 300
  )

  $startInfo = [Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $FilePath
  $startInfo.UseShellExecute = $false
  $startInfo.WorkingDirectory = $RepositoryRoot
  foreach ($argument in $ArgumentList) {
    [void]$startInfo.ArgumentList.Add($argument)
  }
  Write-Step ("Running: {0} {1}" -f $FilePath, ($ArgumentList -join " "))
  $process = [Diagnostics.Process]::Start($startInfo)
  if ($null -eq $process) {
    throw "Failed to start process: $FilePath"
  }
  try {
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
      try {
        $process.Kill($true)
      } catch {
        Write-Warning "Failed to terminate timed-out process $FilePath`: $($_.Exception.Message)"
      }
      throw "Process timed out after $TimeoutSeconds seconds: $FilePath"
    }
    $process.WaitForExit()
    if ($AllowedExitCodes -notcontains $process.ExitCode) {
      throw "Process exited with code $($process.ExitCode): $FilePath"
    }
    return $process.ExitCode
  } finally {
    $process.Dispose()
  }
}

function Wait-ForCondition {
  param(
    [Parameter(Mandatory)][scriptblock]$Condition,
    [Parameter(Mandatory)][string]$Description,
    [int]$TimeoutSeconds = 30
  )
  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    if (& $Condition) {
      return
    }
    Start-Sleep -Milliseconds 250
  } while ([DateTime]::UtcNow -lt $deadline)
  throw "Timed out waiting for $Description"
}

function Get-MigrationHint {
  if (-not (Test-Path -LiteralPath $MigrationRegistryPath)) {
    return $null
  }
  $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Software\studio.shinsekai\Migration")
  if ($null -eq $key) {
    return $null
  }
  try {
    $value = $key.GetValue(
      $MigrationRegistryValue,
      $null,
      [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
    )
    if ($null -eq $value) {
      return $null
    }
    return [PSCustomObject]@{
      Value = [string]$value
      Kind = $key.GetValueKind($MigrationRegistryValue)
    }
  } finally {
    $key.Dispose()
  }
}

function Get-TestShortcutPaths {
  $paths = [Collections.Generic.List[string]]::new()
  foreach ($folder in @(
    [Environment]::GetFolderPath("Desktop"),
    [Environment]::GetFolderPath("CommonDesktopDirectory"),
    [Environment]::GetFolderPath("Programs"),
    [Environment]::GetFolderPath("CommonPrograms")
  )) {
    if ([string]::IsNullOrWhiteSpace($folder)) {
      continue
    }
    [void]$paths.Add((Join-Path $folder "Shinsekai.lnk"))
    [void]$paths.Add((Join-Path $folder "Shinsekai"))
  }
  return @($paths | Select-Object -Unique)
}

function Add-CleanupError {
  param(
    [Parameter(Mandatory)][string]$Description,
    [Parameter(Mandatory)][Management.Automation.ErrorRecord]$ErrorRecord
  )
  $message = "$Description`: $($ErrorRecord.Exception.Message)"
  [void]$CleanupErrors.Add($message)
  Write-Warning $message
}

function Invoke-CleanupAction {
  param(
    [Parameter(Mandatory)][string]$Description,
    [Parameter(Mandatory)][scriptblock]$Action
  )
  try {
    & $Action
  } catch {
    Add-CleanupError -Description $Description -ErrorRecord $_
  }
}

try {
  if (-not $IsWindows) {
    throw "This integration test must run on Windows."
  }
  Assert-Condition ([Environment]::Is64BitOperatingSystem) "the v2.1.0 x64 migration test requires a 64-bit Windows host"
  Assert-Condition (-not [string]::IsNullOrWhiteSpace($ProgramFiles64)) "Program Files could not be resolved"
  Assert-Condition (-not [string]::IsNullOrWhiteSpace($LocalAppData)) "LocalAppData could not be resolved"

  if ([string]::IsNullOrWhiteSpace($NsisInstallerPath)) {
    $installerCandidates = @(
      Get-ChildItem -LiteralPath (Join-Path $FrontendRoot "src-tauri\target\release\bundle\nsis") -Filter "*.exe" -File
    )
    Assert-Condition ($installerCandidates.Count -eq 1) "expected exactly one freshly built NSIS installer, found $($installerCandidates.Count)"
    $NsisInstallerPath = $installerCandidates[0].FullName
  } else {
    $NsisInstallerPath = (Resolve-Path -LiteralPath $NsisInstallerPath).Path
  }
  Assert-Condition (Test-Path -LiteralPath $NsisInstallerPath -PathType Leaf) "NSIS installer does not exist: $NsisInstallerPath"

  Write-Step "Checking that the runner has no pre-existing Shinsekai installation"
  $preexistingEntries = @(Get-ShinsekaiEntries)
  Assert-Condition ($preexistingEntries.Count -eq 0) "the runner already has $($preexistingEntries.Count) Shinsekai uninstall entry or entries"
  foreach ($path in @($ExpectedLegacyInstallDir, $ExpectedNsisInstallDir)) {
    Assert-Condition (-not (Test-Path -LiteralPath $path)) "the runner already contains test-owned path: $path"
  }
  foreach ($registryPath in @($MigrationRegistryPath, $LegacyProductRegistryPath, $NsisUninstallRegistryPath)) {
    Assert-Condition (-not (Test-Path -LiteralPath $registryPath)) "the runner already contains test-owned registry state: $registryPath"
  }
  foreach ($shortcutPath in Get-TestShortcutPaths) {
    Assert-Condition (-not (Test-Path -LiteralPath $shortcutPath)) "the runner already contains a Shinsekai shortcut: $shortcutPath"
  }
  $StudioRegistryParentExisted = Test-Path -LiteralPath $StudioRegistryParentPath
  $LegacyRegistryParentExisted = Test-Path -LiteralPath $LegacyRegistryParentPath
  # From this point onward every mutable path/key was verified absent, so the
  # finally block may safely remove only state created by this test.
  $CleanupAuthorized = $true

  New-Item -ItemType Directory -Path $TestRoot | Out-Null
  $legacyMsiUpdated = Ensure-LegacyMsiFixture `
    -Uri $LegacyMsiUrl `
    -DestinationPath $LegacyMsiPath `
    -ExpectedSha256 $LegacyMsiSha256
  if (-not [string]::IsNullOrWhiteSpace($env:GITHUB_OUTPUT)) {
    Add-Content -LiteralPath $env:GITHUB_OUTPUT -Value (
      "legacy-msi-updated=" + $legacyMsiUpdated.ToString().ToLowerInvariant()
    )
  }
  $actualHash = (Get-FileHash -LiteralPath $LegacyMsiPath -Algorithm SHA256).Hash.ToLowerInvariant()
  Assert-Condition ($actualHash -ceq $LegacyMsiSha256) "legacy MSI SHA-256 mismatch: expected $LegacyMsiSha256, got $actualHash"

  $msiexec = Join-Path $env:SystemRoot "System32\msiexec.exe"
  Write-Step "Installing the real v2.1.0 MSI into its default Program Files location"
  [void](Invoke-CheckedProcess -FilePath $msiexec -ArgumentList @(
    "/i",
    $LegacyMsiPath,
    "/qn",
    "/norestart",
    "REBOOT=ReallySuppress",
    "/L*v",
    $MsiInstallLog
  ) -AllowedExitCodes @(0, 3010) -TimeoutSeconds 180)

  $legacyEntries = @(
    Get-ShinsekaiEntries | Where-Object {
      (Test-MsiEntry -Entry $_) -and (Test-StringEqual -Left $_.DisplayVersion -Right $LegacyVersion)
    }
  )
  Assert-Condition ($legacyEntries.Count -eq 1) "expected exactly one v2.1.0 MSI ARP entry, found $($legacyEntries.Count)"
  $legacyEntry = $legacyEntries[0]
  Assert-Condition ($legacyEntry.HiveName -eq "HKLM") "legacy MSI ARP entry must be machine-wide, found $($legacyEntry.HiveName)"
  Assert-Condition ($legacyEntry.View -eq "Registry64") "legacy x64 MSI ARP entry must use the 64-bit registry view, found $($legacyEntry.View)"
  Assert-Condition (Test-StringEqual -Left $legacyEntry.Publisher -Right "shinsekai") "legacy MSI publisher is $($legacyEntry.Publisher), expected shinsekai"
  Assert-Condition ($legacyEntry.KeyName -match '^\{[0-9A-Fa-f-]{36}\}$') "legacy MSI ARP key is not a product-code GUID: $($legacyEntry.KeyName)"
  $LegacyProductCode = $legacyEntry.KeyName
  $legacyInstallDir = Normalize-InstallPath $legacyEntry.InstallLocation
  Assert-Condition (Test-StringEqual -Left $legacyInstallDir -Right (Normalize-InstallPath $ExpectedLegacyInstallDir)) "legacy MSI did not use default Program Files: $legacyInstallDir"
  Assert-Condition (Test-Path -LiteralPath (Join-Path $legacyInstallDir "shinsekai.exe") -PathType Leaf) "legacy MSI main executable is missing"

  Write-Step "Seeding strong project data in the legacy Program Files project root"
  New-Item -ItemType Directory -Path (Split-Path -Parent $SeedFile) -Force | Out-Null
  [IO.File]::WriteAllText(
    $SeedFile,
    "integration_marker: $SeedToken`n",
    [Text.UTF8Encoding]::new($false)
  )
  Assert-Condition (Test-Path -LiteralPath $SeedFile -PathType Leaf) "failed to create the legacy project-data marker"

  Write-Step "Running the freshly built current-user NSIS through the updater-compatible migration path"
  [void](Invoke-CheckedProcess -FilePath $NsisInstallerPath -ArgumentList @("/P", "/UPDATE", "/NS") -AllowedExitCodes @(0) -TimeoutSeconds 300)

  Wait-ForCondition -Description "the legacy MSI ARP entry to be removed" -Condition {
    $remaining = @(
      Get-ShinsekaiEntries | Where-Object {
        (Test-MsiEntry -Entry $_) -and $_.KeyName -eq $LegacyProductCode
      }
    )
    return $remaining.Count -eq 0
  }

  $allEntriesAfterMigration = @(Get-ShinsekaiEntries)
  $remainingMsiEntries = @($allEntriesAfterMigration | Where-Object { Test-MsiEntry -Entry $_ })
  Assert-Condition ($remainingMsiEntries.Count -eq 0) "legacy MSI ARP state remains after migration"
  $nsisEntries = @(
    $allEntriesAfterMigration | Where-Object {
      (-not (Test-MsiEntry -Entry $_)) -and $_.HiveName -eq "HKCU"
    }
  )
  Assert-Condition ($nsisEntries.Count -eq 1) "expected exactly one current-user NSIS ARP entry, found $($nsisEntries.Count)"
  $nsisEntry = $nsisEntries[0]
  Assert-Condition (Test-StringEqual -Left $nsisEntry.DisplayVersion -Right $CurrentVersion) "new NSIS ARP version is $($nsisEntry.DisplayVersion), expected $CurrentVersion"
  $nsisInstallDir = Normalize-InstallPath $nsisEntry.InstallLocation
  Assert-Condition (Test-StringEqual -Left $nsisInstallDir -Right (Normalize-InstallPath $ExpectedNsisInstallDir)) "new current-user NSIS did not install in LocalAppData: $nsisInstallDir"
  Assert-Condition (-not (Test-StringEqual -Left $nsisInstallDir -Right $legacyInstallDir)) "new current-user NSIS incorrectly inherited the Program Files MSI directory"
  Assert-Condition (Test-Path -LiteralPath (Join-Path $nsisInstallDir "shinsekai.exe") -PathType Leaf) "new NSIS main executable is missing"
  $newUninstaller = Join-Path $nsisInstallDir "uninstall.exe"
  Assert-Condition (Test-Path -LiteralPath $newUninstaller -PathType Leaf) "new NSIS uninstaller is missing"
  Assert-Condition (-not (Test-Path -LiteralPath (Join-Path $legacyInstallDir "shinsekai.exe"))) "legacy MSI executable remains after migration"
  Assert-Condition (Test-Path -LiteralPath $SeedFile -PathType Leaf) "legacy project data was removed during MSI-to-NSIS migration"
  $seedContents = [IO.File]::ReadAllText($SeedFile)
  Assert-Condition ($seedContents.Contains($SeedToken, [StringComparison]::Ordinal)) "legacy project-data marker contents changed during migration"

  $migrationHint = Get-MigrationHint
  Assert-Condition ($null -ne $migrationHint) "MSI migration hint was not written"
  Assert-Condition ($migrationHint.Kind -eq [Microsoft.Win32.RegistryValueKind]::String) "MSI migration hint must be REG_SZ, found $($migrationHint.Kind)"
  $hintPath = Normalize-InstallPath $migrationHint.Value
  Assert-Condition (Test-StringEqual -Left $hintPath -Right $legacyInstallDir) "MSI migration hint does not preserve the legacy app root: $hintPath"

  Write-Step "Uninstalling the migrated current-user NSIS installation"
  [void](Invoke-CheckedProcess -FilePath $newUninstaller -ArgumentList @("/S") -AllowedExitCodes @(0) -TimeoutSeconds 180)
  Wait-ForCondition -Description "the NSIS installation and ARP entry to be removed" -Condition {
    $remainingNsisEntries = @(
      Get-ShinsekaiEntries | Where-Object { -not (Test-MsiEntry -Entry $_) }
    )
    return $remainingNsisEntries.Count -eq 0 -and -not (Test-Path -LiteralPath $ExpectedNsisInstallDir)
  }
  Assert-Condition (Test-Path -LiteralPath $SeedFile -PathType Leaf) "uninstalling the new NSIS unexpectedly removed legacy project data"
  Write-Step "Real v2.1.0 MSI-to-current-NSIS migration passed"
} catch {
  $TestFailure = $_
  Write-Host "::error title=Windows MSI-to-NSIS migration failed::$($_.Exception.Message)"
  if (Test-Path -LiteralPath $MsiInstallLog) {
    Write-Host "::group::MSI install log tail"
    Get-Content -LiteralPath $MsiInstallLog -Tail 120
    Write-Host "::endgroup::"
  }
} finally {
  Write-Step "Cleaning all installer integration-test state"

  if ($CleanupAuthorized) {
    Invoke-CleanupAction -Description "uninstall current-user NSIS" -Action {
      $uninstaller = Join-Path $ExpectedNsisInstallDir "uninstall.exe"
      if (Test-Path -LiteralPath $uninstaller -PathType Leaf) {
        [void](Invoke-CheckedProcess -FilePath $uninstaller -ArgumentList @("/S") -AllowedExitCodes @(0) -TimeoutSeconds 180)
      }
    }

    Invoke-CleanupAction -Description "uninstall legacy MSI" -Action {
      $installedLegacyEntries = @(
        Get-ShinsekaiEntries | Where-Object {
          (Test-MsiEntry -Entry $_) -and (Test-StringEqual -Left $_.DisplayVersion -Right $LegacyVersion)
        }
      )
      foreach ($entry in $installedLegacyEntries) {
        if ($entry.KeyName -notmatch '^\{[0-9A-Fa-f-]{36}\}$') {
          throw "refusing to clean a legacy MSI with a non-GUID ARP key: $($entry.KeyName)"
        }
        [void](Invoke-CheckedProcess -FilePath (Join-Path $env:SystemRoot "System32\msiexec.exe") -ArgumentList @(
          "/x",
          $entry.KeyName,
          "/qn",
          "/norestart",
          "REBOOT=ReallySuppress",
          "/L*v",
          $MsiCleanupLog
        ) -AllowedExitCodes @(0, 1605, 3010) -TimeoutSeconds 180)
      }
    }

    foreach ($path in @($ExpectedNsisInstallDir, $ExpectedLegacyInstallDir)) {
      Invoke-CleanupAction -Description "remove test-owned directory $path" -Action {
        if (Test-Path -LiteralPath $path) {
          Remove-Item -LiteralPath $path -Recurse -Force
        }
      }
    }
    foreach ($shortcutPath in Get-TestShortcutPaths) {
      Invoke-CleanupAction -Description "remove test-owned shortcut $shortcutPath" -Action {
        if (Test-Path -LiteralPath $shortcutPath) {
          Remove-Item -LiteralPath $shortcutPath -Recurse -Force
        }
      }
    }
    foreach ($registryPath in @(
      $NsisUninstallRegistryPath,
      $MigrationRegistryPath,
      $LegacyProductRegistryPath
    )) {
      Invoke-CleanupAction -Description "remove test-owned registry path $registryPath" -Action {
        if (Test-Path -LiteralPath $registryPath) {
          Remove-Item -LiteralPath $registryPath -Recurse -Force
        }
      }
    }
    Invoke-CleanupAction -Description "remove empty test registry parents" -Action {
      foreach ($registryParent in @(
        @{
          Path = $StudioRegistryParentPath
          Existed = $StudioRegistryParentExisted
        },
        @{
          Path = $LegacyRegistryParentPath
          Existed = $LegacyRegistryParentExisted
        }
      )) {
        $registryPath = $registryParent.Path
        if (-not $registryParent.Existed -and (Test-Path -LiteralPath $registryPath)) {
          $item = Get-Item -LiteralPath $registryPath
          if ($item.GetSubKeyNames().Count -eq 0 -and $item.GetValueNames().Count -eq 0) {
            Remove-Item -LiteralPath $registryPath -Force
          }
        }
      }
    }

  }

  Invoke-CleanupAction -Description "remove integration-test temporary files" -Action {
    if (Test-Path -LiteralPath $TestRoot) {
      Remove-Item -LiteralPath $TestRoot -Recurse -Force
    }
  }
  if ($CleanupAuthorized) {
    Invoke-CleanupAction -Description "verify strict cleanup" -Action {
      $remainingEntries = @(Get-ShinsekaiEntries)
      if ($remainingEntries.Count -ne 0) {
        throw "cleanup left $($remainingEntries.Count) Shinsekai ARP entry or entries"
      }
      foreach ($path in @(
        $ExpectedNsisInstallDir,
        $ExpectedLegacyInstallDir,
        $MigrationRegistryPath,
        $LegacyProductRegistryPath,
        $NsisUninstallRegistryPath,
        $TestRoot
      )) {
        if (Test-Path -LiteralPath $path) {
          throw "cleanup left test-owned state: $path"
        }
      }
      foreach ($shortcutPath in Get-TestShortcutPaths) {
        if (Test-Path -LiteralPath $shortcutPath) {
          throw "cleanup left test-owned shortcut state: $shortcutPath"
        }
      }
      if (-not [string]::IsNullOrWhiteSpace($LegacyProductCode)) {
        $legacyArpPath = "Registry::HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Uninstall\$LegacyProductCode"
        if (Test-Path -LiteralPath $legacyArpPath) {
          throw "cleanup left the legacy MSI product-code key: $legacyArpPath"
        }
      }
    }
  }
}

if ($null -ne $TestFailure) {
  throw $TestFailure
}
if ($CleanupErrors.Count -ne 0) {
  throw "Installer integration test cleanup failed: $($CleanupErrors -join '; ')"
}
