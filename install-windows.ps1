# Amplifier Distro - Windows Installer
# Can be compiled to .exe using ps2exe: https://github.com/MScholtes/PS2EXE
#
# To compile:
#   Install-Module ps2exe
#   ps2exe install-windows.ps1 amplifier-distro-installer.exe -noConsole

param(
    [string]$InstallDir = "$env:USERPROFILE\amplifier-distro"
)

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms

function Show-Message {
    param([string]$Message, [string]$Title = "Amplifier Distro Installer")
    [System.Windows.MessageBox]::Show($Message, $Title)
}

function Show-Progress {
    param([string]$Activity, [string]$Status, [int]$PercentComplete)
    Write-Progress -Activity $Activity -Status $Status -PercentComplete $PercentComplete
}

# Welcome
$result = [System.Windows.MessageBox]::Show(
    "Welcome to Amplifier Distro Installer!`n`nThis will install Amplifier Distro to:`n$InstallDir`n`nClick OK to continue or Cancel to exit.",
    "Amplifier Distro Installer",
    [System.Windows.MessageBoxButton]::OKCancel,
    [System.Windows.MessageBoxImage]::Information
)

if ($result -eq [System.Windows.MessageBoxResult]::Cancel) {
    exit
}

try {
    # Check Docker
    Show-Progress "Checking Prerequisites" "Checking Docker..." 10

    if (!(Get-Command docker -ErrorAction SilentlyContinue)) {
        $result = [System.Windows.MessageBox]::Show(
            "Docker Desktop is not installed.`n`nWould you like to download it now?",
            "Docker Required",
            [System.Windows.MessageBoxButton]::YesNo,
            [System.Windows.MessageBoxImage]::Warning
        )

        if ($result -eq [System.Windows.MessageBoxResult]::Yes) {
            Start-Process "https://www.docker.com/products/docker-desktop"
        }
        exit
    }

    # Check Docker is running
    Show-Progress "Checking Prerequisites" "Checking Docker status..." 20

    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Show-Message "Docker is not running.`n`nPlease start Docker Desktop and try again." "Docker Not Running"
        exit
    }

    # Download/Clone repository
    Show-Progress "Downloading" "Downloading Amplifier Distro..." 30

    if (Test-Path $InstallDir) {
        $result = [System.Windows.MessageBox]::Show(
            "Directory already exists:`n$InstallDir`n`nDelete and reinstall?",
            "Directory Exists",
            [System.Windows.MessageBoxButton]::YesNo,
            [System.Windows.MessageBoxImage]::Question
        )

        if ($result -eq [System.Windows.MessageBoxResult]::Yes) {
            Remove-Item -Recurse -Force $InstallDir
        } else {
            exit
        }
    }

    # Clone or download
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Show-Progress "Downloading" "Cloning repository..." 40
        git clone https://github.com/ramparte/amplifier-distro.git $InstallDir
    } else {
        Show-Progress "Downloading" "Downloading ZIP..." 40
        $zipPath = "$env:TEMP\amplifier-distro.zip"
        Invoke-WebRequest -Uri "https://github.com/ramparte/amplifier-distro/archive/refs/heads/main.zip" -OutFile $zipPath

        Show-Progress "Downloading" "Extracting..." 50
        Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\amplifier-distro-temp"
        Move-Item "$env:TEMP\amplifier-distro-temp\amplifier-distro-main" $InstallDir
        Remove-Item $zipPath
        Remove-Item "$env:TEMP\amplifier-distro-temp" -Recurse
    }

    # Build containers
    Show-Progress "Building" "Building Docker containers..." 60

    Set-Location $InstallDir

    $process = Start-Process -FilePath "docker" -ArgumentList "compose --profile all build" -NoNewWindow -PassThru -Wait

    if ($process.ExitCode -ne 0) {
        Show-Message "Build failed. Check Docker and try again." "Build Error"
        exit
    }

    # Start containers
    Show-Progress "Starting" "Starting services..." 80

    $process = Start-Process -FilePath "docker" -ArgumentList "compose --profile all up -d" -NoNewWindow -PassThru -Wait

    if ($process.ExitCode -ne 0) {
        Show-Message "Failed to start services. Check Docker and try again." "Start Error"
        exit
    }

    # Wait for installation
    Show-Progress "Finalizing" "Installing packages..." 90
    Start-Sleep -Seconds 15

    # Success message
    Show-Progress "Complete" "Installation complete!" 100

    $result = [System.Windows.MessageBox]::Show(
        "Installation complete!`n`nAmplifier Distro is now running.`n`nClick OK to launch the TUI.",
        "Installation Complete",
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Information
    )

    # Launch TUI
    Start-Process -FilePath "docker" -ArgumentList "compose exec tui amplifier-tui" -NoNewWindow

} catch {
    Show-Message "Installation failed:`n$($_.Exception.Message)" "Error"
    exit 1
}
