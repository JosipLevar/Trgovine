from flask import Flask, jsonify, render_template_string
import requests
from datetime import datetime, timedelta
import json
from threading import Lock

app = Flask(__name__)

cache = {
    'data': None,
    'timestamp': None,
    'date': None
}
cache_lock = Lock()

CACHE_DURATION_HOURS = 6

MY_STORES = {
    'spar': [
        {'id': 38, 'name': 'SPAR Gospodska'},
        {'id': 7, 'name': 'INTERSPAR King Cross'}
    ],
    'konzum': [
        {'id': 48, 'name': 'Konzum Bolnička'},
        {'id': 216, 'name': 'Super Konzum Huzjanova'}
    ],
    'kaufland': [
        {'id': 'HR5630', 'name': 'Kaufland Jankomir'}
    ]
}

def get_next_sunday():
    today = datetime.now()
    days_ahead = 6 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days_ahead)

def is_cache_valid():
    if cache['data'] is None or cache['timestamp'] is None:
        return False
    
    now = datetime.now()
    next_sunday = get_next_sunday().date()
    
    if cache['date'] != next_sunday:
        return False
    
    time_diff = now - cache['timestamp']
    if time_diff.total_seconds() > CACHE_DURATION_HOURS * 3600:
        return False
    
    return True

def check_spar():
    """Provjeri Spar trgovine"""
    results = []
    
    # Dodaj fallback za sve trgovine odmah
    for my_store in MY_STORES['spar']:
        results.append({
            'chain': 'SPAR',
            'name': my_store['name'],
            'open': False,
            'hours': 'Provjeravam...'
        })
    
    try:
        print("Checking Spar...")
        url = "https://www.spar.hr/lokacije/_jcr_content.stores.v2.html"
        params = {'latitude': 45.8133064, 'longitude': 15.8867033, 'radius': 40}
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        all_stores = response.json()
        
        print(f"Spar API returned {len(all_stores)} stores")
        
        next_sunday = get_next_sunday()
        results = []  # Reset nakon uspješnog API poziva
        
        for my_store in MY_STORES['spar']:
            found = False
            for store in all_stores:
                if store.get('locationId') == my_store['id']:
                    found = True
                    is_closed = False
                    
                    for special in store.get('specialShopHours', []):
                        if special.get('dayType'):
                            try:
                                special_date = datetime(
                                    special['dayType']['year'],
                                    special['dayType']['month'] + 1,
                                    special['dayType']['dayOfMonth']
                                )
                                if special_date.date() == next_sunday.date() and special.get('from1') is None:
                                    is_closed = True
                                    break
                            except Exception as e:
                                print(f"Error parsing special hours: {e}")
                                continue
                    
                    if not is_closed:
                        for hours in store.get('shopHours', []):
                            if hours.get('dayType') == 'nedjelja':
                                from_h = hours['from1']['hourOfDay']
                                from_m = hours['from1']['minute']
                                to_h = hours['to1']['hourOfDay']
                                to_m = hours['to1']['minute']
                                results.append({
                                    'chain': 'SPAR',
                                    'name': my_store['name'],
                                    'open': True,
                                    'hours': f"{from_h:02d}:{from_m:02d} - {to_h:02d}:{to_m:02d}"
                                })
                                break
                    else:
                        results.append({
                            'chain': 'SPAR',
                            'name': my_store['name'],
                            'open': False,
                            'hours': 'Zatvoreno'
                        })
                    break
            
            if not found:
                results.append({
                    'chain': 'SPAR',
                    'name': my_store['name'],
                    'open': False,
                    'hours': 'Trgovina ne postoji u bazi'
                })
                
    except Exception as e:
        print(f"Spar error: {e}")
        # Vrati fallback s greškom
        results = []
        for my_store in MY_STORES['spar']:
            results.append({
                'chain': 'SPAR',
                'name': my_store['name'],
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })
    
    return results

def check_konzum():
    """Provjeri Konzum trgovine"""
    results = []
    
    # Fallback
    for my_store in MY_STORES['konzum']:
        results.append({
            'chain': 'KONZUM',
            'name': my_store['name'],
            'open': False,
            'hours': 'Provjeravam...'
        })
    
    try:
        print("Checking Konzum...")
        url = "https://trgovine.konzum.hr/api/locations/"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        print(f"Konzum API response type: {type(data)}")
        
        if isinstance(data, dict):
            all_stores = data.get('locations', []) or data.get('data', []) or []
        elif isinstance(data, list):
            all_stores = data
        else:
            all_stores = []
        
        print(f"Konzum stores found: {len(all_stores)}")
        
        results = []  # Reset
        
        for my_store in MY_STORES['konzum']:
            found = False
            for store in all_stores:
                if store.get('id') == my_store['id']:
                    found = True
                    if store.get('open_this_sunday'):
                        work_hours_str = store.get('work_hours', '[]')
                        try:
                            work_hours = json.loads(work_hours_str)
                            for day in work_hours:
                                if day.get('name') == 'Nedjelja' and day.get('from_hour'):
                                    from_time = day['from_hour'].split('T')[1][:5]
                                    to_time = day['to_hour'].split('T')[1][:5]
                                    results.append({
                                        'chain': 'KONZUM',
                                        'name': my_store['name'],
                                        'open': True,
                                        'hours': f"{from_time} - {to_time}"
                                    })
                                    break
                        except Exception as e:
                            print(f"Konzum parse error: {e}")
                            results.append({
                                'chain': 'KONZUM',
                                'name': my_store['name'],
                                'open': False,
                                'hours': 'Greška u parsiranju'
                            })
                    else:
                        results.append({
                            'chain': 'KONZUM',
                            'name': my_store['name'],
                            'open': False,
                            'hours': 'Zatvoreno'
                        })
                    break
            
            if not found:
                results.append({
                    'chain': 'KONZUM',
                    'name': my_store['name'],
                    'open': False,
                    'hours': 'Trgovina ne postoji u bazi'
                })
                
    except Exception as e:
        print(f"Konzum error: {e}")
        results = []
        for my_store in MY_STORES['konzum']:
            results.append({
                'chain': 'KONZUM',
                'name': my_store['name'],
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })
    
    return results

def check_kaufland():
    """Provjeri Kaufland trgovine"""
    results = []
    
    for my_store in MY_STORES['kaufland']:
        try:
            print(f"Checking Kaufland {my_store['id']}...")
            url = f"https://www.kaufland.hr/.klstorebygeo.storeName={my_store['id']}.json"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            store = response.json()
            
            for day in store.get('wod', []):
                if day.startswith('Sunday'):
                    parts = day.split('|')
                    if len(parts) == 3:
                        from_time = parts[1]
                        to_time = parts[2]
                        if from_time == '00:00' and to_time == '00:00':
                            results.append({
                                'chain': 'KAUFLAND',
                                'name': my_store['name'],
                                'open': False,
                                'hours': 'Zatvoreno'
                            })
                        else:
                            results.append({
                                'chain': 'KAUFLAND',
                                'name': my_store['name'],
                                'open': True,
                                'hours': f"{from_time} - {to_time}"
                            })
                    break
        except Exception as e:
            print(f"Kaufland error: {e}")
            results.append({
                'chain': 'KAUFLAND',
                'name': my_store['name'],
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })
    
    return results

def check_lidl():
    """Provjeri Lidl trgovine"""
    results = []
    
    # Fallback
    for my_store in MY_STORES['lidl']:
        results.append({
            'chain': 'LIDL',
            'name': my_store['name'],
            'open': False,
            'hours': 'Provjeravam...'
        })
    
    try:
        print("Checking Lidl...")
        url = "https://live.api.schwarz/odj/stores-api/v2/myapi/stores-frontend/stores"
        params = {
            'limit': 100,
            'offset': 0,
            'country_code': 'HR',
            'geo_box': '45.6:15.7:46.0:16.0'
        }
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        all_stores = data.get('results', [])
        
        print(f"Lidl stores found: {len(all_stores)}")
        
        next_sunday = get_next_sunday().strftime('%Y-%m-%d')
        results = []  # Reset
        
        for my_store in MY_STORES['lidl']:
            found = False
            for store in all_stores:
                if store.get('objectNumber') == my_store['id']:
                    found = True
                    opening_hours = store.get('openingHours', {}).get('items', [])
                    for day in opening_hours:
                        if day.get('date') == next_sunday:
                            time_ranges = day.get('timeRanges', [])
                            if time_ranges:
                                from_time = time_ranges[0]['from'].split('T')[1][:5]
                                to_time = time_ranges[0]['to'].split('T')[1][:5]
                                results.append({
                                    'chain': 'LIDL',
                                    'name': my_store['name'],
                                    'open': True,
                                    'hours': f"{from_time} - {to_time}"
                                })
                            else:
                                results.append({
                                    'chain': 'LIDL',
                                    'name': my_store['name'],
                                    'open': False,
                                    'hours': 'Zatvoreno'
                                })
                            break
                    break
            
            if not found:
                results.append({
                    'chain': 'LIDL',
                    'name': my_store['name'],
                    'open': False,
                    'hours': 'Trgovina ne postoji u bazi'
                })
                
    except Exception as e:
        print(f"Lidl error: {e}")
        results = []
        for my_store in MY_STORES['lidl']:
            results.append({
                'chain': 'LIDL',
                'name': my_store['name'],
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })
    
    return results

def fetch_fresh_data():
    """Dohvati podatke sa svih API-ja"""
    print("=== FETCHING FRESH DATA ===")
    next_sunday = get_next_sunday()
    
    results = []
    results.extend(check_spar())
    results.extend(check_konzum())
    results.extend(check_kaufland())
    
    print(f"Total stores: {len(results)}")
    
    results.sort(key=lambda x: (not x['open'], x['chain'], x['name']))
    
    return {
        'success': True,
        'date': next_sunday.strftime('%d.%m.%Y'),
        'day': 'Nedjelja',
        'stores': results,
        'summary': {
            'open': len([s for s in results if s['open']]),
            'closed': len([s for s in results if not s['open']]),
            'total': len(results)
        },
        'cached': False,
        'last_update': datetime.now().strftime('%H:%M')
    }

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/check')
def check_all():
    try:
        with cache_lock:
            if is_cache_valid():
                result = cache['data'].copy()
                result['cached'] = True
                return jsonify(result)
            else:
                data = fetch_fresh_data()
                cache['data'] = data
                cache['timestamp'] = datetime.now()
                cache['date'] = get_next_sunday().date()
                return jsonify(data)
                
    except Exception as e:
        print(f"API check error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="hr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Radi li u nedjelju?</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 15px;
        }
        
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        
        h1 {
            color: #333;
            font-size: 1.8em;
            margin-bottom: 5px;
        }
        
        .subtitle {
            color: #666;
            font-size: 0.9em;
            margin-bottom: 20px;
        }
        
        .date-banner {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 15px;
        }
        
        .cache-info {
            text-align: center;
            font-size: 0.8em;
            color: #999;
            margin-bottom: 15px;
        }
        
        .cache-info.cached { color: #4CAF50; }
        
        .summary {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .summary-card {
            flex: 1;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }
        
        .summary-card.open { background: #e8f5e9; color: #2e7d32; }
        .summary-card.closed { background: #ffebee; color: #c62828; }
        .summary-card .number { font-size: 2em; font-weight: bold; }
        .summary-card .label { font-size: 0.85em; margin-top: 5px; }
        
        .store {
            padding: 15px;
            border-bottom: 1px solid #f0f0f0;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .store:last-child { border-bottom: none; }
        
        .store-icon {
            font-size: 2em;
            min-width: 40px;
            text-align: center;
        }
        
        .store-info {
            flex: 1;
        }
        
        .store-chain {
            font-size: 0.75em;
            color: #999;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .store-name {
            font-size: 1.1em;
            font-weight: 600;
            color: #333;
            margin: 2px 0;
        }
        
        .store-hours {
            font-size: 0.9em;
            padding: 4px 10px;
            border-radius: 12px;
            display: inline-block;
            margin-top: 4px;
        }
        
        .store-hours.open {
            background: #4CAF50;
            color: white;
        }
        
        .store-hours.closed {
            background: #f44336;
            color: white;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .error {
            background: #ffebee;
            color: #c62828;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
        }
        
        .refresh-btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 1em;
            width: 100%;
            margin-top: 15px;
            font-weight: 600;
            transition: transform 0.2s;
        }
        
        .refresh-btn:active {
            transform: scale(0.98);
        }
        
        .footer {
            text-align: center;
            margin-top: 20px;
            color: white;
            font-size: 0.85em;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛒 Radi li u nedjelju?</h1>
        <p class="subtitle">Moje trgovine u Zagrebu</p>
        
        <div id="results">
            <div class="loading">
                <div class="spinner"></div>
                Učitavam podatke...
            </div>
        </div>
        
        <button class="refresh-btn" onclick="loadData()">🔄 Osvježi podatke</button>
    </div>
    
    <div class="footer">
        Podaci se cachiraju 6 sati
    </div>
    
    <script>
        function loadData() {
            document.getElementById('results').innerHTML = `
                <div class="loading">
                    <div class="spinner"></div>
                    Učitavam podatke...
                </div>
            `;
            
            fetch('/api/check')
                .then(response => response.json())
                .then(data => {
                    if (!data.success) {
                        throw new Error(data.error || 'Nepoznata greška');
                    }
                    
                    const cacheStatus = data.cached ? 
                        `💾 Cached podaci (${data.last_update})` : 
                        `🔄 Osvježeno (${data.last_update})`;
                    
                    let html = `
                        <div class="date-banner">
                            📅 ${data.day}, ${data.date}
                        </div>
                        
                        <div class="cache-info ${data.cached ? 'cached' : ''}">
                            ${cacheStatus}
                        </div>
                        
                        <div class="summary">
                            <div class="summary-card open">
                                <div class="number">${data.summary.open}</div>
                                <div class="label">RADI</div>
                            </div>
                            <div class="summary-card closed">
                                <div class="number">${data.summary.closed}</div>
                                <div class="label">ZATVORENO</div>
                            </div>
                        </div>
                    `;
                    
                    data.stores.forEach(store => {
                        const icon = store.open ? '✅' : '❌';
                        const statusClass = store.open ? 'open' : 'closed';
                        
                        html += `
                            <div class="store">
                                <div class="store-icon">${icon}</div>
                                <div class="store-info">
                                    <div class="store-chain">${store.chain}</div>
                                    <div class="store-name">${store.name}</div>
                                    <span class="store-hours ${statusClass}">${store.hours}</span>
                                </div>
                            </div>
                        `;
                    });
                    
                    document.getElementById('results').innerHTML = html;
                })
                .catch(error => {
                    document.getElementById('results').innerHTML = `
                        <div class="error">
                            <strong>⚠️ Greška:</strong><br>
                            ${error.message}
                        </div>
                    `;
                });
        }
        
        loadData();
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
