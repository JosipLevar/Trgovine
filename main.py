from flask import Flask, jsonify, render_template_string, send_from_directory, request
import requests
from datetime import datetime, timedelta
import json
from threading import Lock
from bs4 import BeautifulSoup
import os
from pathlib import Path
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

app = Flask(__name__, static_folder='static', static_url_path='/static')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

BASE_DIR = Path(__file__).parent

def static_version() -> str:
    static_dir = BASE_DIR / "static"
    if not static_dir.exists():
        return "1"
    latest = 0
    for root, _, files in os.walk(static_dir):
        for f in files:
            path = Path(root) / f
            try:
                mtime = int(path.stat().st_mtime)
                if mtime > latest:
                    latest = mtime
            except OSError:
                continue
    return str(latest or 1)

STATIC_VERSION = static_version()

cache = {'data': None, 'timestamp': None, 'date': None, 'user': None}
cache_lock = Lock()
CACHE_DURATION_HOURS = 6

JOSIP_STORES = {
    'spar': [
        {'id': 38, 'name': 'SPAR Gospodska'},
        {'id': 7,  'name': 'SPAR King Cross'},
        {'id': 2,  'name': 'City Center West'}
    ],
    'konzum': [
        {'id': 48,  'name': 'Konzum Bolnička'},
        {'id': 216, 'name': 'Konzum Huzjanova'}
    ],
    'kaufland': [
        {'id': 'HR5630', 'name': 'Kaufland Jankomir'}
    ],
    'studenac': [
        {
            'name': 'Studenac Gospodska',
            'url': 'https://www.studenac.hr/trgovine/1578/t1715-zagreb'
        },
        {
            'name': 'Studenac Dudovec',
            'url': 'https://www.studenac.hr/trgovine/1507/t1568-zagreb'
        },
        {
            'name': 'Studenac Bolnička',
            'url': 'https://www.studenac.hr/trgovine/1543/t1687-zagreb'
        }
    ]
}

NINA_STORES = {
    'konzum': [
        {'id': 200, 'name': 'Konzum Šibice'}
    ],
    'dm': [
        {'storeId': 'K095', 'name': 'DM Zaprešić'}
    ],
    'muller': [
            {'storeId': '5089', 'name': 'Müller Zaprešić'}
    ],
    'plodine': [
        {
            'name': 'Plodine Zaprešić',
            'url': 'https://www.plodine.hr/supermarketi/90/hipermarket-zapresic?select=90'
        }
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

def check_spar(stores_config):
    results = []
    spar_stores = stores_config.get('spar', [])
    
    for my_store in spar_stores:
        results.append({
            'chain': 'SPAR',
            'name': my_store['name'],
            'open': False,
            'hours': 'Provjeravam...'
        })

    try:
        print("Checking Spar...")
        url = "https://www.spar.hr/lokacije/_jcr_content.stores.v2.html"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        all_stores = response.json()
        print(f"Spar API returned {len(all_stores)} stores")

        next_sunday = get_next_sunday().date()
        results = []

        for my_store in spar_stores:
            my_id = str(my_store['id'])
            found = False

            for store in all_stores:
                loc_id = str(store.get('locationId'))
                if loc_id != my_id:
                    continue

                found = True
                sunday_from = None
                sunday_to = None

                for item in store.get('shopHours', []):
                    oh = item.get('openingHours', {})
                    if oh.get('dayType') == 'nedjelja':
                        from1 = oh.get('from1')
                        to1 = oh.get('to1')
                        if from1 and to1:
                            sunday_from = (from1['hourOfDay'], from1['minute'])
                            sunday_to = (to1['hourOfDay'], to1['minute'])
                        break

                closed_override = False
                for special in store.get('specialShopHours', []):
                    oh = special.get('openingHours', {})
                    day = oh.get('dayType')
                    if not day:
                        continue

                    try:
                        special_date = datetime(
                            day['year'],
                            day['month'] + 1,
                            day['dayOfMonth']
                        ).date()
                    except Exception as e:
                        print(f"SPAR special date parse error: {e}")
                        continue

                    if special_date != next_sunday:
                        continue

                    from1 = oh.get('from1')
                    to1 = oh.get('to1')
                    if from1 is None and to1 is None:
                        closed_override = True
                        sunday_from = None
                        sunday_to = None
                    elif from1 and to1:
                        sunday_from = (from1['hourOfDay'], from1['minute'])
                        sunday_to = (to1['hourOfDay'], to1['minute'])
                    break

                if sunday_from and sunday_to:
                    from_h, from_m = sunday_from
                    to_h, to_m = sunday_to
                    results.append({
                        'chain': 'SPAR',
                        'name': my_store['name'],
                        'open': True,
                        'hours': f"{from_h:02d}:{from_m:02d} - {to_h:02d}:{to_m:02d}"
                    })
                else:
                    status = 'Zatvoreno' if closed_override or sunday_from is None else 'Nema podataka'
                    results.append({
                        'chain': 'SPAR',
                        'name': my_store['name'],
                        'open': False,
                        'hours': status
                    })
                break

            if not found:
                results.append({
                    'chain': 'SPAR',
                    'name': my_store['name'],
                    'open': False,
                    'hours': 'Trgovina ne postoji u API-ju'
                })

    except Exception as e:
        print(f"Spar error: {e}")
        results = []
        for my_store in spar_stores:
            results.append({
                'chain': 'SPAR',
                'name': my_store['name'],
                'open': False,
                'hours': f'Greška: {str(e)[:40]}'
            })

    return results


def check_konzum(stores_config):
    results = []
    konzum_stores = stores_config.get('konzum', [])
    
    for my_store in konzum_stores:
        results.append({'chain': 'KONZUM', 'name': my_store['name'], 'open': False, 'hours': 'Provjeravam...'})
    
    try:
        print("Checking Konzum...")
        url = "https://trgovine.konzum.hr/api/locations/"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, dict):
            all_stores = data.get('locations', []) or data.get('data', []) or []
        elif isinstance(data, list):
            all_stores = data
        else:
            all_stores = []
        
        results = []
        for my_store in konzum_stores:
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
                                    results.append({'chain': 'KONZUM', 'name': my_store['name'], 'open': True, 'hours': f"{from_time} - {to_time}"})
                                    break
                        except Exception as e:
                            print(f"Konzum parse error: {e}")
                            results.append({'chain': 'KONZUM', 'name': my_store['name'], 'open': False, 'hours': 'Greska'})
                    else:
                        results.append({'chain': 'KONZUM', 'name': my_store['name'], 'open': False, 'hours': 'Zatvoreno'})
                    break
            if not found:
                results.append({'chain': 'KONZUM', 'name': my_store['name'], 'open': False, 'hours': 'Trgovina ne postoji'})
    except Exception as e:
        print(f"Konzum error: {e}")
        results = []
        for my_store in konzum_stores:
            results.append({'chain': 'KONZUM', 'name': my_store['name'], 'open': False, 'hours': f'Greska: {str(e)[:30]}'})
    return results

def check_kaufland(stores_config):
    results = []
    kaufland_stores = stores_config.get('kaufland', [])
    
    for my_store in kaufland_stores:
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
                            results.append({'chain': 'KAUFLAND', 'name': my_store['name'], 'open': False, 'hours': 'Zatvoreno'})
                        else:
                            results.append({'chain': 'KAUFLAND', 'name': my_store['name'], 'open': True, 'hours': f"{from_time} - {to_time}"})
                    break
        except Exception as e:
            print(f"Kaufland error: {e}")
            results.append({'chain': 'KAUFLAND', 'name': my_store['name'], 'open': False, 'hours': f'Greska: {str(e)[:30]}'})
    return results


def check_studenac(stores_config):
    results = []
    studenac_stores = stores_config.get('studenac', [])

    for my_store in studenac_stores:
        name = my_store['name']
        url = my_store['url']

        try:
            print(f"Scraping Studenac HTML: {url}")
            resp = requests.get(url, timeout=15, headers=HEADERS)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')
            work_hours_div = soup.find('div', class_='marketsingleworkhours')
            if not work_hours_div:
                lis = soup.find_all('li')
            else:
                lis = work_hours_div.find_all('li')

            sunday_text = None
            for li in lis:
                txt = li.get_text(separator=' ', strip=True)
                if 'Nedjelja' in txt:
                    sunday_text = txt
                    break

            if not sunday_text:
                results.append({
                    'chain': 'STUDENAC',
                    'name': name,
                    'open': False,
                    'hours': 'Nema informacija'
                })
                continue

            if 'Zatvoreno' in sunday_text:
                results.append({
                    'chain': 'STUDENAC',
                    'name': name,
                    'open': False,
                    'hours': 'Zatvoreno'
                })
            else:
                match = re.search(r'(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})', sunday_text)
                if match:
                    from_time = match.group(1).replace('.', ':')
                    to_time = match.group(2).replace('.', ':')
                    results.append({
                        'chain': 'STUDENAC',
                        'name': name,
                        'open': True,
                        'hours': f'{from_time} - {to_time}'
                    })
                else:
                    results.append({
                        'chain': 'STUDENAC',
                        'name': name,
                        'open': True,
                        'hours': 'Otvoreno'
                    })

        except Exception as e:
            print(f"Studenac scrape error for {url}: {e}")
            results.append({
                'chain': 'STUDENAC',
                'name': name,
                'open': False,
                'hours': f'Greška: {str(e)[:40]}'
            })

    return results

def check_dm(stores_config):
    results = []
    dm_stores = stores_config.get('dm', [])
    next_sunday = get_next_sunday().date()

    for my_store in dm_stores:
        store_id = my_store['storeId']
        name = my_store['name']
        
        try:
            print(f"Checking DM {store_id} via API...")
            url = f"https://store-data-service.services.dmtech.com/stores/item/{store_id}"
            response = requests.get(url, timeout=15, headers=HEADERS)
            response.raise_for_status()
            store_data = response.json()
            
            print(f"DM API: Got response for {store_id}")
            
            # Check standard opening hours (weekDay: 0 or 7 = Sunday)
            sunday_hours = None
            for hours in store_data.get('openingHours', []):
                if hours.get('weekDay') in [0, 7]:
                    time_ranges = hours.get('timeRanges', [])
                    if time_ranges:
                        sunday_hours = time_ranges[0]
                        print(f"DM: Found Sunday in openingHours: {sunday_hours}")
                    break
            
            # Check extraOpeningDays for this specific Sunday
            for extra_day in store_data.get('extraOpeningDays', []):
                try:
                    extra_date = datetime.strptime(extra_day['date'], '%Y-%m-%d').date()
                    if extra_date == next_sunday:
                        time_ranges = extra_day.get('timeRanges', [])
                        if time_ranges:
                            sunday_hours = time_ranges[0]
                            print(f"DM: Found Sunday in extraOpeningDays: {sunday_hours}")
                        break
                except:
                    continue
            
            # Check extraClosingDates
            is_closed = False
            for closing_date in store_data.get('extraClosingDates', []):
                try:
                    close_date = datetime.strptime(closing_date['date'], '%Y-%m-%d').date()
                    if close_date == next_sunday:
                        is_closed = True
                        print(f"DM: Found Sunday in extraClosingDates - closed")
                        break
                except:
                    continue
            
            if is_closed or not sunday_hours:
                results.append({
                    'chain': 'DM',
                    'name': name,
                    'open': False,
                    'hours': 'Zatvoreno'
                })
            else:
                results.append({
                    'chain': 'DM',
                    'name': name,
                    'open': True,
                    'hours': f"{sunday_hours['opening']} - {sunday_hours['closing']}"
                })
                
        except Exception as e:
            print(f"DM API error for {store_id}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'chain': 'DM',
                'name': name,
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })
    
    return results




def check_muller(stores_config):
    results = []
    muller_stores = stores_config.get('muller', [])

    # Müller GraphQL API credentials
    muller_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'hr-HR,hr;q=0.9,en-US;q=0.8,en;q=0.7',
        'Authorization': 'Basic V3BaMGdPOURURlpFZXVRSTpZUHhsZmxyVWlmQnpbWGhC',
        'Content-Type': 'application/json',
        'Origin': 'https://www.mueller.hr',
        'Referer': 'https://www.mueller.hr/'
    }

    for my_store in muller_stores:
        store_id = my_store['storeId']
        name = my_store['name']
        
        try:
            print(f"Checking Müller {store_id} via GraphQL API...")
            
            url = "https://backend.prod.ecom.mueller.hr/"
            params = {
                'operatingChain': 'B2C_HR_Store',
                'operationName': 'GetStoreById',
                'variables': json.dumps({
                    'storeId': store_id,
                    'country': 'HR'
                }),
                'extensions': json.dumps({
                    'persistedQuery': {
                        'version': 1,
                        'sha256Hash': '194353aba88b0d1d9c6a83a8860b1fb99f509edf26b21b77b09e950120cbb9db'
                    }
                })
            }
            
            response = requests.get(url, params=params, headers=muller_headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            print(f"Müller API: Got response for {store_id}")
            
            store_data = data.get('data', {}).get('getStoreById', {})
            opening_hours = store_data.get('openingHours', [])
            
            # Find Sunday hours
            sunday_hours = None
            for hours in opening_hours:
                if hours.get('day') == 'sunday':
                    sunday_hours = hours
                    break
            
            if sunday_hours:
                opening = sunday_hours.get('openingTime')
                closing = sunday_hours.get('closingTime')
                
                if opening and closing:
                    print(f"Müller: Found Sunday hours: {opening} - {closing}")
                    results.append({
                        'chain': 'MÜLLER',
                        'name': name,
                        'open': True,
                        'hours': f'{opening} - {closing}'
                    })
                else:
                    results.append({
                        'chain': 'MÜLLER',
                        'name': name,
                        'open': False,
                        'hours': 'Zatvoreno'
                    })
            else:
                print(f"Müller: Sunday not found - closed")
                results.append({
                    'chain': 'MÜLLER',
                    'name': name,
                    'open': False,
                    'hours': 'Zatvoreno'
                })
                
        except Exception as e:
            print(f"Müller API error for {store_id}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'chain': 'MÜLLER',
                'name': name,
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })
    
    return results



def check_plodine(stores_config):
    results = []
    plodine_stores = stores_config.get('plodine', [])

    for my_store in plodine_stores:
        name = my_store['name']
        url = my_store['url']

        try:
            print(f"Scraping Plodine HTML: {url}")
            # Add SSL verification disable and more robust headers
            resp = requests.get(
                url, 
                timeout=20, 
                headers=HEADERS,
                verify=False,  # SSL bypass
                allow_redirects=True
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Find working hours section
            hours_found = False
            
            # Plodine uses specific class or structure - look for opening hours
            for tag in soup.find_all(['div', 'table', 'ul', 'li', 'p', 'span', 'td']):
                text = tag.get_text(separator=' ', strip=True)
                
                if 'Nedjelja' in text or 'nedjelja' in text or 'NEDJELJA' in text:
                    # Check if closed
                    if 'Zatvoreno' in text or 'zatvoreno' in text or 'ZATVORENO' in text:
                        results.append({
                            'chain': 'PLODINE',
                            'name': name,
                            'open': False,
                            'hours': 'Zatvoreno'
                        })
                        hours_found = True
                        break
                    else:
                        # Try to find hours near Sunday
                        match = re.search(r'(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2})', text)
                        if match:
                            from_time = match.group(1).replace('.', ':')
                            to_time = match.group(2).replace('.', ':')
                            results.append({
                                'chain': 'PLODINE',
                                'name': name,
                                'open': True,
                                'hours': f'{from_time} - {to_time}'
                            })
                            hours_found = True
                            break
            
            if not hours_found:
                # Default: closed if we can't find info
                results.append({
                    'chain': 'PLODINE',
                    'name': name,
                    'open': False,
                    'hours': 'Zatvoreno'
                })

        except requests.exceptions.SSLError as e:
            print(f"Plodine SSL error for {url}: {e}")
            results.append({
                'chain': 'PLODINE',
                'name': name,
                'open': False,
                'hours': 'SSL greška'
            })
        except requests.exceptions.Timeout as e:
            print(f"Plodine timeout for {url}: {e}")
            results.append({
                'chain': 'PLODINE',
                'name': name,
                'open': False,
                'hours': 'Timeout'
            })
        except Exception as e:
            print(f"Plodine scrape error for {url}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'chain': 'PLODINE',
                'name': name,
                'open': False,
                'hours': f'Greška: {str(e)[:30]}'
            })

    return results

def fetch_fresh_data(user='josip'):
    print(f"=== FETCHING FRESH DATA FOR {user.upper()} ===")
    next_sunday = get_next_sunday()
    
    stores_config = JOSIP_STORES if user == 'josip' else NINA_STORES

    results = []
    results.extend(check_spar(stores_config))
    results.extend(check_konzum(stores_config))
    results.extend(check_kaufland(stores_config))
    results.extend(check_studenac(stores_config))
    results.extend(check_dm(stores_config))
    results.extend(check_muller(stores_config))
    results.extend(check_plodine(stores_config))

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


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Radi li u nedjelju?</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    background: #f3f4f6;
    min-height: 100vh;
    padding: 15px;
}

.container {
    max-width: 600px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
}
h1{color:#333;font-size:1.8em;margin-bottom:5px}
.subtitle{color:#666;font-size:0.9em;margin-bottom:20px}
.user-toggle{display:flex;gap:10px;margin-bottom:20px;border-radius:8px;background:#f0f0f0;padding:4px}
.toggle-btn{flex:1;padding:10px;border:none;background:transparent;border-radius:6px;cursor:pointer;font-weight:600;transition:all 0.2s}
.toggle-btn.active{background:#2563eb;color:white;box-shadow:0 2px 8px rgba(37,99,235,0.3)}
.toggle-btn:not(.active){color:#666}
.date-banner{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:15px;border-radius:10px;text-align:center;font-size:1.1em;font-weight:bold;margin-bottom:15px}
.cache-info{text-align:center;font-size:0.8em;color:#999;margin-bottom:15px}
.cache-info.cached{color:#4CAF50}
.summary{display:flex;gap:10px;margin-bottom:20px}
.summary-card{flex:1;padding:12px;border-radius:8px;text-align:center}
.summary-card.open{background:#e8f5e9;color:#2e7d32}
.summary-card.closed{background:#ffebee;color:#c62828}
.summary-card .number{font-size:2em;font-weight:bold}
.summary-card .label{font-size:0.85em;margin-top:5px}
.store{padding:15px;border-bottom:1px solid #f0f0f0;display:flex;align-items:center;gap:12px}
.store:last-child{border-bottom:none}
.store-icon{font-size:2em;min-width:40px;text-align:center}
.store-info{flex:1}
.store-chain{font-size:0.75em;color:#999;text-transform:uppercase;letter-spacing:0.5px}
.store-name{font-size:1.1em;font-weight:600;color:#333;margin:2px 0}
.store-hours{font-size:0.9em;padding:4px 10px;border-radius:12px;display:inline-block;margin-top:4px}
.store-hours.open{background:#4CAF50;color:white}
.store-hours.closed{background:#f44336;color:white}
.loading{text-align:center;padding:40px;color:#666}
.spinner{border:3px solid #f3f3f3;border-top:3px solid #667eea;border-radius:50%;width:40px;height:40px;animation:spin 1s linear infinite;margin:0 auto 15px}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
.error{background:#ffebee;color:#c62828;padding:15px;border-radius:8px;margin:20px 0}
.refresh-btn {
    background: #2563eb;
    color: white;
    border: none;
    padding: 12px 25px;
    border-radius: 999px;
    cursor: pointer;
    font-size: 1em;
    width: 100%;
    margin-top: 15px;
    font-weight: 600;
    transition: transform 0.15s, box-shadow 0.15s;
    box-shadow: 0 4px 12px rgba(37,99,235,0.25);
}

.refresh-btn:active {
    transform: translateY(1px);
    box-shadow: 0 2px 6px rgba(37,99,235,0.35);
}
.footer {
    text-align: center;
    margin-top: 20px;
    color: #6b7280;
    font-size: 0.85em;
}
</style>
</head>
<body>
<div class="container">
<h1>🛒 Radi li u nedjelju?</h1>
<p class="subtitle">Moje trgovine u Zagrebu</p>
<div class="user-toggle">
  <button class="toggle-btn" data-user="josip">Josip</button>
  <button class="toggle-btn" data-user="nina">Nina</button>
</div>
<div id="results"><div class="loading"><div class="spinner"></div>Učitavam podatke...</div></div>
<button class="refresh-btn" onclick="loadData()">🔄 Osvježi podatke</button>
</div>
<div class="footer">Podaci se cachiraju 6 sati</div>
<script src="/static/app.js?v=__VERSION__"></script>
</body>
</html>'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE.replace('__VERSION__', STATIC_VERSION))

@app.route('/api/check')
def check_all():
    user = request.args.get('user', 'josip')
    print(f"=== API CHECK CALLED for {user} ===")
    
    try:
        with cache_lock:
            if is_cache_valid() and cache.get('user') == user:
                print("Cache is valid, returning cached data")
                result = cache['data'].copy()
                result['cached'] = True
                return jsonify(result)
            else:
                print("Cache invalid or different user, fetching fresh data...")
                data = fetch_fresh_data(user)
                cache['data'] = data
                cache['timestamp'] = datetime.now()
                cache['date'] = get_next_sunday().date()
                cache['user'] = user
                print("Fresh data fetched successfully")
                return jsonify(data)
    except Exception as e:
        print(f"API check error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
