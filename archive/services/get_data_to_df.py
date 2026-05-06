import pandas as pd
from services.epias_service import EpiasService

def get_mcp_dataframe(start_date, end_date):
    """
    Servisten gelen ham veriyi temiz bir DataFrame'e dönüştürür.
    """
    service = EpiasService()
    raw_data = service.fetch_mcp_data(start_date, end_date)
    
    if not raw_data:
        return pd.DataFrame() # Boşsa boş DF döndür

    df = pd.DataFrame(raw_data)
    
    # Veri Tiplerini Düzenle
    df['date'] = pd.to_datetime(df['date'])
    
    # ML modelleri ve grafik için sıralama
    df = df.sort_values('date').reset_index(drop=True)
    
    return df

# --- TEST VE ÇALIŞTIRMA ---
if __name__ == "__main__":
    # Örnek: Yarının tarihi (Sistem zamanına göre 2026-05-04)
    target = "2026-05-04"
    
    print(f"{target} için veri çekiliyor...")
    df = get_mcp_dataframe(target, target)
    
    if not df.empty:
        # Saat sütunu ekle
        df['hour'] = df['date'].dt.strftime('%H:%M')
        
        # Tabloyu göster
        print(f"\n--- {target} PTF DEĞERLERİ ---")
        # EPİAŞ'tan gelen fiyat sütunu genelde 'price' ismindedir
        print(df[['hour', 'price']].to_string(index=False))
        
        # İstersen burada CSV olarak da kaydedebilirsin
        # df.to_csv(f"ptf_{target}.csv", index=False)
    else:
        print("\n!!! Veri alınamadı !!!")
        print("İpucu: Cookie süresi dolmuş olabilir. Tarayıcıdan yeni bir Cookie alıp epias_service.py dosyasına yapıştırın.")