# PowerShell script to sync openclaw/skills to Docker container
# Equivalent to sync-skills.sh

$SkillName = $args[0]
$ContainerName = "openclaw-openclaw-cli-1"

if ($SkillName) {
    Write-Host "📦 Syncing specific skill: $SkillName to $ContainerName..." -ForegroundColor Cyan
    # Check if directory exists
    if (Test-Path ".\openclaw\skills\$SkillName") {
        docker cp ".\openclaw\skills\$SkillName\." "$($ContainerName):/app/skills/$SkillName/"
    } else {
        Write-Error "Skill directory not found: .\openclaw\skills\$SkillName"
        exit 1
    }
} else {
    Write-Host "📦 Syncing all skills to $ContainerName..." -ForegroundColor Cyan
    docker cp .\openclaw\skills\. "$($ContainerName):/app/skills/"
}

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Skills synced successfully!" -ForegroundColor Green
} else {
    Write-Error "Sync failed with exit code $LASTEXITCODE"
}

Write-Host "`nUsage:"
Write-Host "  .\sync-skills.ps1           # Sync all"
Write-Host "  .\sync-skills.ps1 <skill>   # Sync specific skill"
