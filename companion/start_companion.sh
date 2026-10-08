#!/usr/bin/env bash
set -e
echo "============================================================"
echo " Hand Gesture Control — Desktop Companion"
echo "============================================================"
echo ""
echo "Installing required packages..."
pip install -r requirements.txt --quiet
echo ""
echo "Starting companion server on ws://127.0.0.1:8765 ..."
echo 'Open your deployed website and click "Try Live Demo".'
echo "Press Ctrl+C to stop."
echo ""
python gesture_companion.py
