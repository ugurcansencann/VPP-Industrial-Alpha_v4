import requests
from datetime import datetime, timedelta

def fetch_tomorrow_ptf():
    """EPİAŞ'tan yarınki fiyatları ham liste olarak çeker."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    url = "https://seffaflik.epias.com.tr/transparency/service/market/day-ahead-mcp"
    params = {"startDate": tomorrow, "endDate": tomorrow, "displayLanguage": "tr"}
    
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            # Sadece fiyat listesini döndürür
            return response.json().get('body', {}).get('dayAheadMCPList', [])
    except Exception:
        return []
    return []