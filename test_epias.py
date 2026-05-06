import requests
import json
import urllib3
from datetime import datetime

# SSL uyarılarını kapatıyoruz (verify=False kullanımı için)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class EpiasService:
    def __init__(self):
        # Postman'dan teyit ettiğimiz en güncel servis adresi
        self.url = "https://seffaflik.epias.com.tr/electricity-service/v1/markets/dam/data/mcp"
        
        # Postman'dan kopyaladığın başlıklar (Burayı güncellemen gerekebilir)
        self.headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'tr-TR',
            'Content-Type': 'application/json',
            'Origin': 'https://seffaflik.epias.com.tr',
            'Referer': 'https://seffaflik.epias.com.tr/electricity/electricity-markets/day-ahead-market-dam/market-clearing-price-mcp',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
            'Cookie': 'epias-security-redirect-count=2; TS017622c9=01cbc7c0b2fcb756fcce9b9f55c859d9b8b87c556450dbc20431ff29352a98e26a15c0880c1833e6153f43eb2e72688f5c9b8804c26c9ec44ccc1c4aa0591238ebfc22e05e; TGTA-EXT-PROD=xc2i8c3LqUNfQIZQDUO1tYt05Ep8lWfXwZuZsr1vyJmJfKRtfgDpxOZfL2uhY4aIDjp/VBdzzMFMnzu28GbQ6knDvqNalMYf7gSrnXkC+8GV4RVAqaqD8D4UCQA33LZ8iBwLspkp5AphiPkQ8ilb5w==; TS01beeb54=01cbc7c0b28808bfee5beec57c7fcf227b7ff8877d3c5e67508515633c0ac4faf41bd9c72c20d5eb3b59f1aaaef15f3c3c1d6b221bec6b9d8f20f4006d17b3d50748d73d37a708757c4ef7f87fee0ada130b6f849a; TS01beeb54=01cbc7c0b26388266ed7d20cf9ea090239e123b3f29c92c0664ec3ea7efff4494df96ab6e60fad18bf7e7e786183fb1fa9959ac7fff385a7bc0b7077f6fd3133289f692369'
        }

    def fetch_mcp_data(self, start_date, end_date):
        """
        Girdi: '2026-05-04' (YYYY-MM-DD)
        Çıktı: List of dict (Veri listesi)
        """
        # EPİAŞ'ın istediği ISO formatına dönüştürme
        iso_start = f"{start_date}T00:00:00+03:00"
        iso_end = f"{end_date}T00:00:00+03:00"

        payload = json.dumps({
            "startDate": iso_start,
            "endDate": iso_end,
            "page": {
                "number": 1,
                "size": 2000, # Backfill için büyük bir rakam tutuyoruz
                "sort": {"direction": "ASC", "field": "date"}
            }
        })

        try:
            # Postman'ın verdiği POST isteğini yapıyoruz
            response = requests.post(
                self.url, 
                headers=self.headers, 
                data=payload, 
                verify=False, 
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                # Yeni altyapıda veriler 'items' altında geliyor
                return data.get('items', [])
            else:
                print(f"EPİAŞ Hatası: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            print(f"Bağlantı Hatası: {e}")
            return []

# Test kullanımı
if __name__ == "__main__":
    service = EpiasService()
    test_data = service.fetch_mcp_data("2026-05-04", "2026-05-04")
    print(f"Test Sonucu: {len(test_data)} adet veri çekildi.")