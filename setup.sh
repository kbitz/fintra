#!/bin/bash
set -e

cd "$(dirname "$0")"

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo ""
echo "Setup complete. Activate with: source venv/bin/activate"
echo "Set your API key:  export MASSIVE_API_KEY='your_key'"
echo "Run:               python fintra.py"
