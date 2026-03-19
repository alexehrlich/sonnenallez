from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import requests
import json
from datetime import datetime
import pytz
import pandas as pd
import threading
import time
import logging

flask_logger = logging.getLogger('werkzeug')
flask_logger.setLevel(logging.ERROR)

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

def fetch_with_retry(url, retries=3, retry_sleep_time=5):
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return json.loads(r.text)
        except Exception as e:
            if attempt < retries -1:
                time.sleep(retry_sleep_time)
            else:
                raise

def get_next_departures(stop_id: str):
    try:
        response_json = fetch_with_retry(
            f"https://v6.bvg.transport.rest/stops/{stop_id}/departures?duration={TIMEWINDOW_MIN}"
            )
    except Exception as e:
        print(f"Failed to fetch API data for stop id: {stop_id}: {e}")
        return pd.DataFrame()
    
    rows = []
    now = datetime.now(pytz.timezone('Europe/Berlin'))
    for d in response_json.get('departures', []):
        try:
            if not d.get('when') or not d.get('plannedWhen'):
                print("'when' or 'plannedWhen' empty in API call - departure gets ignores")
                continue
            when_time = datetime.fromisoformat(d['when'])
            planned_time = datetime.fromisoformat(d['plannedWhen'])
            time_left = int((when_time - now).total_seconds())
            
            if time_left < 0:
                continue
            
            minutes, seconds = divmod(time_left, 60)
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
        except Exception as e:
            print(f"Skipping departure due to unexpected data: {e} | raw: {d}")
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
        finally:
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