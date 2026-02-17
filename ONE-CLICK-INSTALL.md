# Amplifier Distro - One-Click Installation

Get from zero to TUI in seconds with our one-click installer.

## Quick Install

### Linux / macOS / WSL

Copy and paste this into your terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```

Or with wget:

```bash
wget -qO- https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.sh | bash
```

### Windows

**Option 1: PowerShell (Coming Soon)**
```powershell
iwr -useb https://raw.githubusercontent.com/ramparte/amplifier-distro/main/install.ps1 | iex
```

**Option 2: Double-click installer**
Download and run: `scripts\start-dev.bat`

## What Happens?

The installer:

1. **Checks prerequisites** - Verifies Docker and Docker Compose are installed and running
2. **Downloads the repo** - Clones or downloads the amplifier-distro repository
3. **Builds containers** - Creates images for all interfaces (CLI, TUI, GUI, Voice)
4. **Starts services** - Launches all containers in the background
5. **Opens the TUI** - Automatically launches the Terminal UI interface

## After Installation

Once the TUI is running, you can:

- **Use Amplifier immediately** - Start chatting with the AI
- **Exit and restart** - `docker compose exec tui amplifier-tui`
- **Access other interfaces**:
  - CLI: `docker compose exec cli bash`
  - Web GUI: Open http://localhost:8400 in your browser
  - Voice: Coming soon

## Customization

### Install Location

By default, installs to `~/amplifier-distro`. To change:

```bash
AMPLIFIER_INSTALL_DIR=~/my-custom-location curl -fsSL https://... | bash
```

### API Keys

Add your API keys in `.env.local`:

```bash
cd ~/amplifier-distro
echo 'ANTHROPIC_API_KEY=sk-ant-your-key' >> .env.local
echo 'OPENAI_API_KEY=sk-your-key' >> .env.local
```

Then restart:

```bash
bash scripts/stop-dev.sh
bash scripts/start-dev.sh
```

## Troubleshooting

### Docker not running

```
ERROR: Docker is not running.
```

**Solution:** Start Docker Desktop or the Docker daemon.

### Permission denied

```
ERROR: Permission denied while trying to connect to Docker daemon
```

**Solution:** Add your user to the docker group:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Port already in use

```
ERROR: Port 8400 is already allocated
```

**Solution:** Stop the service using that port or change the port in `docker-compose.yml`.

## Manual Installation

If you prefer manual control, see [INSTRUCTIONS.md](INSTRUCTIONS.md) for detailed setup instructions.

## Uninstall

To completely remove Amplifier Distro:

```bash
cd ~/amplifier-distro
bash scripts/stop-dev.sh
cd ..
rm -rf amplifier-distro
docker volume prune -f
```

## Web-Based Installer

For a prettier installation experience, visit:

**https://YOUR_ORG.github.io/amplifier-distro/install.html**

This provides:
- Platform detection (Linux/Mac/Windows)
- Copy-to-clipboard install commands
- Visual progress indicators
- Troubleshooting tips
