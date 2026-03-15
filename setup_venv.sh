DIRECTORY='.venv'

if [ ! -d "$DIRECTORY" ]; then
    echo "$DIRECTORY does not exist. Creating..."
    python3 -m venv .venv --system-site-packages
    .venv/bin/pip install -r requirements.txt
fi
