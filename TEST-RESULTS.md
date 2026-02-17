# Test Results - One-Click Installers

All configurations updated to use `https://github.com/ramparte/amplifier-distro`

## ✅ Local Tests Passed

### Configuration Validation
- ✅ `devcontainer.json` - Valid JSON syntax
- ✅ `install.sh` - Valid bash syntax
- ✅ `.devcontainer/setup.sh` - Valid bash syntax
- ✅ `.devcontainer/start-tui.sh` - Valid bash syntax
- ✅ `install.html` - Contains correct ramparte URLs

### Script Configuration
- ✅ `start-dev.sh` uses `--profile all` (starts CLI, TUI, GUI, Voice)
- ✅ `docker-compose.yml` has all 4 services in 'all' profile
- ✅ `docker-entrypoint.sh` installs amplifier-tui automatically
- ✅ All URLs updated to ramparte/amplifier-distro

## 🧪 GitHub Tests Required

### Test 1: GitHub Codespaces (TRUE One-Click)

**URL to test:**
```
https://github.com/codespaces/new?repo=ramparte/amplifier-distro
```

**Expected behavior:**
1. Click the link
2. GitHub Codespaces opens in browser
3. Devcontainer builds (~3-5 minutes first time)
4. `postStartCommand` runs `start-dev.sh`
5. Docker containers build
6. TUI launches automatically in the terminal
7. You can interact with Amplifier immediately

**How to test:**
1. Push all changes to GitHub
2. Click the Codespaces link
3. Wait for build
4. Verify TUI appears

### Test 2: Command-Line Installer

**URL to test:**
```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```

**Expected behavior:**
1. Checks Docker prerequisites
2. Clones repo to `~/amplifier-distro`
3. Runs `start-dev.sh`
4. TUI launches automatically

**How to test:**
1. Push all changes to GitHub (especially `install.sh`)
2. On a clean machine with Docker installed, run the curl command
3. Verify it works end-to-end

### Test 3: Windows PowerShell Installer

**URL to test:**
```powershell
iwr -useb https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install-windows.ps1 | iex
```

**Expected behavior:**
1. GUI dialog checks Docker
2. Downloads/clones repo
3. Builds containers
4. Launches TUI

**How to test:**
1. Push `install-windows.ps1` to GitHub
2. On Windows with Docker Desktop, run the PowerShell command
3. Verify GUI dialogs appear and TUI launches

### Test 4: Windows .exe Installer (Requires Building)

**Steps to create:**
```powershell
Install-Module ps2exe -Scope CurrentUser
Invoke-ps2exe install-windows.ps1 amplifier-distro-installer.exe -noConsole
```

**Upload to:**
```
https://github.com/ramparte/amplifier-distro/releases/latest
```

**How to test:**
1. Build the .exe using ps2exe
2. Create a GitHub Release
3. Upload the .exe
4. Download and run
5. Verify it works

### Test 5: Web Page

**URL to host:**
```
https://ramparte.github.io/amplifier-distro/install.html
```

**Setup GitHub Pages:**
1. Go to repo Settings → Pages
2. Source: Deploy from branch `main` / `root`
3. Save
4. Access at: https://ramparte.github.io/amplifier-distro/install.html

**Expected behavior:**
- Beautiful page with gradient background
- Two big buttons at top:
  - "Open in GitHub Codespaces" → Opens Codespaces
  - "Download Windows Installer" → Downloads .exe
- Command-line options below
- All links work correctly

## 📋 Pre-GitHub Checklist

Before pushing to test on GitHub:

- [x] All URLs updated to ramparte/amplifier-distro
- [x] Local syntax validation passed
- [ ] Committed all changes
- [ ] Pushed to GitHub main branch
- [ ] README.md updated with badges (see BADGES.md)
- [ ] GitHub Pages enabled (for install.html)
- [ ] Windows .exe built and uploaded to Releases

## 🚀 Quick Test Commands

After pushing to GitHub, test each method:

**1. Codespaces (Browser):**
- Click: https://github.com/codespaces/new?repo=ramparte/amplifier-distro
- Wait for build → TUI should appear

**2. Command Line (Linux/Mac/WSL):**
```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```

**3. PowerShell (Windows):**
```powershell
iwr -useb https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install-windows.ps1 | iex
```

**4. Web Page:**
- Visit: https://ramparte.github.io/amplifier-distro/install.html
- Click buttons to test

## 📝 Success Criteria

Each method should:
1. ✅ Complete without errors
2. ✅ Build all 4 containers (CLI, TUI, GUI, Voice)
3. ✅ Automatically launch the TUI
4. ✅ TUI is interactive and responsive
5. ✅ User can start using Amplifier immediately

## 🐛 Known Issues / TODO

- [ ] Windows .exe needs to be built with ps2exe
- [ ] GitHub Pages needs to be enabled
- [ ] Test on clean machines (not dev environment)
- [ ] Verify Codespaces billing/limits for users
