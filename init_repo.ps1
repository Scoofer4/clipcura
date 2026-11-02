# Založí lokální git repozitář a veřejný repozitář na GitHubu.
# Předpoklad: nainstalovaný git a GitHub CLI (winget install GitHub.cli) a přihlášení: gh auth login
# Použití (v rozbalené složce):  .\init_repo.ps1 -Owner <uzivatel-nebo-organizace>

param(
    [Parameter(Mandatory = $true)][string]$Owner,     # GitHub účet nebo organizace
    [string]$Name = "clipsana"                     # název repozitáře
)
$ErrorActionPreference = "Stop"

# Kontrola nástrojů
foreach ($tool in "git", "gh") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Chybí $tool – nainstaluj ho a spusť skript znovu." }
}
gh auth status | Out-Null

# Lokální repozitář s výchozí větví main
git init -b main
git add .
git commit -m "Initial scaffold: spec, structure, profiles, prototype, CI"

# Soukromý repozitář na GitHubu, nastavení remote a push
gh repo create "$Owner/$Name" --public --source . --remote origin --push `
    --description "Every clip edit-ready: check and fix footage for DaVinci Resolve (GUI + MCP)"

Write-Host "Hotovo: https://github.com/$Owner/$Name"
