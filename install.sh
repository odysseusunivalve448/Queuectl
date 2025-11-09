#!/bin/bash

# queuectl Installation Script
# Automated setup for queuectl job queue system

set -e

echo "==============================================="
echo "     QUEUECTL INSTALLATION SCRIPT"
echo "==============================================="
echo

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Found Python $python_version"
echo

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 not found. Please install pip first."
    exit 1
fi
echo "✓ pip3 is available"
echo

# Install dependencies
echo "Installing dependencies..."
pip3 install -r requirements.txt
echo "✓ Dependencies installed"
echo

# Install queuectl in editable mode
echo "Installing queuectl..."
pip3 install -e .
echo "✓ queuectl installed"
echo

# Verify installation
echo "Verifying installation..."
if command -v queuectl &> /dev/null; then
    echo "✓ queuectl command is available"
    echo
    queuectl --help
else
    echo "❌ queuectl command not found"
    exit 1
fi

echo
echo "==============================================="
echo "     INSTALLATION COMPLETE!"
echo "==============================================="
echo
echo "Quick Start:"
echo "  1. queuectl enqueue '{\"command\":\"echo Hello\"}'"
echo "  2. queuectl worker start"
echo "  3. queuectl status"
echo
echo "Run demo:"
echo "  ./demo.sh"
echo
echo "Run tests:"
echo "  python3 tests/test_scenarios.py"
echo
echo "For more information, see README.md"
echo