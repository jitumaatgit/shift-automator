#!/bin/bash

# OpenCode Session Export Script
# Usage: ./scripts/export-session.sh [sessionID]

set -e

# Get session ID from argument or use the most recent session
if [ -n "$1" ]; then
    SESSION_ID="$1"
else
    SESSION_ID=$(opencode session list | head -n 2 | tail -n 1 | awk '{print $1}')
fi

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Set output directory
OUTPUT_DIR=".opencode-sessions/sessions"
mkdir -p "$OUTPUT_DIR"

# Export session
echo "Exporting session: $SESSION_ID"
opencode export "$SESSION_ID" --sanitize 2>&1 | tee "$OUTPUT_DIR/ses_${TIMESTAMP}.json" > /dev/null

echo "Exported to: $OUTPUT_DIR/ses_${TIMESTAMP}.json"
echo "Session ID: $SESSION_ID"
echo "Timestamp: $TIMESTAMP"
