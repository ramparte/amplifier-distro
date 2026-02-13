# One-Click Install Badges

Add these to your README.md for easy access:

## GitHub Codespaces (Browser-based, no local install)

```markdown
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?repo=ramparte/amplifier-distro)
```

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?repo=ramparte/amplifier-distro)

## Download Installer

```markdown
[![Download Windows Installer](https://img.shields.io/badge/Download-Windows%20Installer-blue?style=for-the-badge&logo=windows)](https://github.com/ramparte/amplifier-distro/releases/latest/download/amplifier-distro-installer.exe)
```

[![Download Windows Installer](https://img.shields.io/badge/Download-Windows%20Installer-blue?style=for-the-badge&logo=windows)](https://github.com/ramparte/amplifier-distro/releases/latest/download/amplifier-distro-installer.exe)

## Quick Install Command

```markdown
```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```
```

## Example README Section

```markdown
# Amplifier Distro

## 🚀 One-Click Install

### Option 1: GitHub Codespaces (Fastest - No local install)

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?repo=ramparte/amplifier-distro)

Click the badge above and the TUI will open automatically in your browser!

### Option 2: Windows Installer

[![Download Windows Installer](https://img.shields.io/badge/Download-Windows%20Installer-blue?style=for-the-badge&logo=windows)](https://github.com/ramparte/amplifier-distro/releases/latest/download/amplifier-distro-installer.exe)

Download and double-click to install.

### Option 3: Command Line

**Linux / macOS / WSL:**
```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```

**Windows PowerShell:**
```powershell
iwr -useb https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install-windows.ps1 | iex
```
```

## How to Build the Windows .exe

To create the downloadable Windows installer:

1. Install ps2exe:
```powershell
Install-Module ps2exe -Scope CurrentUser
```

2. Build the exe:
```powershell
Invoke-ps2exe install-windows.ps1 amplifier-distro-installer.exe `
    -title "Amplifier Distro Installer" `
    -description "One-click installer for Amplifier Distro" `
    -company "Amplifier" `
    -version "0.1.0" `
    -copyright "© 2025" `
    -iconFile "logo.ico" `
    -noConsole
```

3. Upload to GitHub Releases

## Deploy to GitHub Pages

To host the install.html page:

1. Enable GitHub Pages in repository settings
2. Set source to "main" branch, "/ (root)" folder
3. Access at: `https://YOUR_ORG.github.io/amplifier-distro/install.html`

Or use the install.html directly in your docs folder.
