import requests
import json
import pandas as pd

class EpiasService:
    def __init__(self):
        self.url = "https://seffaflik.epias.com.tr/electricity-service/v1/markets/dam/data/mcp"
        
        # --- HER GÜN BURADAKİ COOKIE DEĞERİNİ GÜNCELLE ---
        self.my_cookie = "TGTA-EXT-PROD=Ptb8M8DQNWDhKGVRN6oFEfzzEUlwhQsX4KCd3c3gQJyoxyxUuaNR0s336mimWpbBl4/AeA5kCZcvtR52FRoqPQMLijgS7CuQi8vKVYc+AFXRzyGkFG7Nwgtihv86DDDJAjUFwrzLGZFVQYCvabz9Ew==; TS01beeb54=01cbc7c0b2091d44496a5bae02e56674545659036a0c538cd09408680aca1e6ec38cddc052d27d1a2b9c5c527d64932b13590565254a63b6e5063589fea0c379d644f7c8203c9eb92f9ac10504b5091ca014609c7b"

    def fetch_mcp_data(self, start_date, end_date):
        headers = {
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'Cookie': self.my_cookie,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        payload = {
            "startDate": f"{start_date}T00:00:00+03:00",
            "endDate": f"{end_date}T23:59:59+03:00",
            "page": {
                "number": 1,
                "size": 2000,
                "sort": {"direction": "ASC", "field": "date"}
            }
        }
        

        try:
            # EPİAŞ bazen SSL sertifikası hatası verebilir, verify=False ekliyoruz
            response = requests.post(self.url, headers=headers, json=payload, verify=False, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                return data.get('items', [])
            else:
                print(f"EPİAŞ Hatası ({response.status_code}): {response.text}")
                return []
        except Exception as e:
            print(f"Bağlantı Hatası: {e}")
            return []