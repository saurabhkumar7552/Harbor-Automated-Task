param([Parameter(Mandatory=$true)][string]$Repository)
# Run manually after review. This installer refuses to overwrite existing files.
$ErrorActionPreference = 'Stop'
$factorySource = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$repositoryTarget = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $Repository).ProviderPath)
if (-not (Test-Path -LiteralPath (Join-Path $repositoryTarget 'tasks') -PathType Container)) {
    throw 'Target must be the benchmark project directory containing tasks/.'
}
if ($repositoryTarget.TrimEnd('\') -eq $factorySource.TrimEnd('\')) { throw 'Source and target must differ.' }
$allFiles = Get-ChildItem -LiteralPath $factorySource -Recurse -File | Where-Object {
    $_.FullName -notmatch '\\(__pycache__|factory-output|build|dist)\\' -and $_.Name -ne '.gitignore'
}
$copyPlan = foreach ($file in $allFiles) {
    $relativeFile = $file.FullName.Substring($factorySource.TrimEnd('\').Length + 1)
    $targetFile = [IO.Path]::GetFullPath((Join-Path $repositoryTarget $relativeFile))
    if (-not $targetFile.StartsWith($repositoryTarget.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Target escaped the repository boundary.'
    }
    if (Test-Path -LiteralPath $targetFile) { throw "Refusing overwrite: $targetFile" }
    $ancestor = Split-Path -Parent $targetFile
    while ($ancestor -and $ancestor.StartsWith($repositoryTarget, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $ancestor) {
            $item = Get-Item -LiteralPath $ancestor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point: $ancestor" }
        }
        if ($ancestor -eq $repositoryTarget) { break }
        $ancestor = Split-Path -Parent $ancestor
    }
    [PSCustomObject]@{ Source=$file.FullName; Target=$targetFile }
}
foreach ($copyEntry in $copyPlan) {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $copyEntry.Target)) | Out-Null
    [IO.File]::Copy($copyEntry.Source, $copyEntry.Target, $false)
}
Write-Output "Copied $($copyPlan.Count) files to $repositoryTarget. Existing task files were not touched."
Write-Output 'Review config/models.yaml, then run scripts/stem-factory.ps1 doctor.'
