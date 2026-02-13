#!/bin/bash
# Devcontainer setup script - runs once after container creation

set -e

echo "========================================"
echo "Setting up Amplifier Distro..."
echo "========================================"

# Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# Make scripts executable
chmod +x scripts/*.sh

# Create .env.local with placeholder keys if it doesn't exist
if [ ! -f .env.local ]; then
    cat > .env.local <<EOF
# Add your API keys here
# ANTHROPIC_API_KEY=sk-ant-your-key
# OPENAI_API_KEY=sk-your-key
EOF
fi

echo "✓ Setup complete!"
echo ""
echo "Starting Docker services in background..."

# Start Docker daemon if not running
if ! docker info &> /dev/null; then
    sudo service docker start
    sleep 3
fi

echo "✓ Docker ready"
