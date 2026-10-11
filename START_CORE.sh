#!/bin/sh
cd "$(dirname "$0")" || exit 1
SMAGA_ENV=development SMAGA_PORT=8788 SMAGA_DEMO_MODE=1 python3 server.py
