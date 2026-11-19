#!/usr/bin/env bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.10+ is required (python.org)."; exit 1; }
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
python -m pip install -q -r requirements.txt
( sleep 2; (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:5000) || (command -v open >/dev/null && open http://127.0.0.1:5000) ) >/dev/null 2>&1 &
python app.py
