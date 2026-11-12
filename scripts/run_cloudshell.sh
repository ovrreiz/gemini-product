#!/usr/bin/env bash
# Запуск у Cloud Shell: потім натисніть «Web Preview» -> «Preview on port 8080».
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt
exec streamlit run app.py --server.port 8080 --server.address 0.0.0.0 \
     --server.enableCORS=false --server.enableXsrfProtection=false
