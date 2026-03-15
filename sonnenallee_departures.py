from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
from datetime import datetime
import pytz
import pandas as pd
import threading
import time

app = Flask(__name__, static_folder='.')
CORS(app)

STOPS = {
    "Erkstraße": "900075101",
    "U Rathaus Neukölln": "900078102",
}
TIMEWINDOW_MIN = 15
FETCH_INTERVAL_SEC = 10

# Shared state
last_result = {"departures": [], "time": "--:--:--", "date": "--.--.----"}
lock = threading.Lock()

def fetch(url):
    r = requests.get(url, timeout=10)
    return json.loads(r.text)

def get_next_departures(stop_id: str):
    response_json = fetch(f"https://v6.bvg.transport.rest/stops/{stop_id}/departures?duration={TIMEWINDOW_MIN}")
    rows = []
    now = datetime.now(pytz.timezone('Europe/Berlin'))
    for d in response_json.get('departures', []):
        try:
            when_time = datetime.fromisoformat(d['when'])
            planned_time = datetime.fromisoformat(d['plannedWhen'])
            time_left = int((when_time - now).total_seconds())
            minutes = time_left // 60
            seconds = time_left % 60
            leaves_in = f"{minutes:02d}:{seconds:02d}"
            if stop_id == "900078102" and d['line']['name'] != "U7":
                continue
            rows.append({
                'line': d['line']['name'],
                'direction': d['direction'],
                'minutes': minutes,
                'seconds': seconds,
                'leaves_in': leaves_in,
                'actual_departure': when_time,
                'planned_departure': planned_time,
            })
        except Exception:
            continue
    return pd.DataFrame(rows)

def fetch_loop():
    global last_result
    while True:
        try:
            now = datetime.now(pytz.timezone('Europe/Berlin'))
            frames = []
            for stop_name, stop_id in STOPS.items():
                df = get_next_departures(stop_id)
                if not df.empty:
                    df['stop'] = stop_name
                    frames.append(df)

            if frames:
                complete = pd.concat(frames).reset_index(drop=True)
                complete = complete[~complete['leaves_in'].str.contains('-')]
                filtered = (
                    complete
                    .sort_values('actual_departure')
                    .groupby(['line', 'direction'])
                    .head(3)
                    .sort_values(['minutes', 'seconds'])
                )
                result = filtered[['line', 'direction', 'minutes', 'seconds', 'leaves_in', 'stop']].to_dict(orient='records')
            else:
                result = []

            with lock:
                last_result = {
                    'departures': result,
                    'time': now.strftime('%H:%M:%S'),
                    'date': now.strftime('%d.%m.%Y'),
                }
        except Exception as e:
            print(f"Fetch error: {e}")

        time.sleep(FETCH_INTERVAL_SEC)

@app.route('/api/departures')
def departures():
    with lock:
        return jsonify(last_result)

@app.route('/')
def index():
    return send_from_directory('.', 'sonnenallee_departures.html')

if __name__ == '__main__':
    t = threading.Thread(target=fetch_loop, daemon=True)
    t.start()
    print("BVG Abfahrtsmonitor startet...")
    app.run(host='0.0.0.0', port=5001, debug=False)