import numpy as np
from sqlalchemy import delete
from pulp import LpProblem, LpMinimize, LpVariable, value, PULP_CBC_CMD

def calculate_vpp_optimization(predicted_load: float, ptf: float, smf: float = None):
    """
    Doğrusal Programlama (PuLP) kullanarak maliyet minimizasyonu yapar.
    Endpoint içindeki tüm mantık buraya taşındı.
    """
    # DEBUG: Terminale değerleri basarak hangisinin None olduğunu gör
    print(f"DEBUG -> Load: {predicted_load}, PTF: {ptf}, SMF: {smf}")
    # Eğer load None gelirse direkt 0 kabul et veya hata fırlat
    # Güvenlik önlemi: Eğer değerler None ise hataya düşmemek için 0.0'a çek
    if predicted_load is None: predicted_load = 0.0
    if ptf is None: ptf = 0.0
    # 1. Maliyet Analizi (SMF varsa ve PTF'den büyükse onu baz al)
    actual_cost = smf if (smf and smf > ptf) else ptf
    
    # 2. Kritik Durum Belirleme (Enerji açığı/fazlası analizi)
    is_critical = True if (smf and smf > ptf * 1.2) else False
    
    # 3. Esneklik Limitlerini Belirle
    # Kritik durumda %30'a kadar kısıntı yapabiliriz, stabil durumda %15.
    flex_limit = 0.70 if is_critical else 0.85 
    
    # 4. Doğrusal Programlama (PuLP)
    prob = LpProblem("Maliyet_Minimizasyonu", LpMinimize)
    
    # Değişken: Optimal Tüketim (Alt sınır esneklik limiti, üst sınır tahmin edilen yük)
    consumption_var = LpVariable("Optimal_Tuketim", 
                                 lowBound=predicted_load * flex_limit, 
                                 upBound=predicted_load)
    
    # Amaç Fonksiyonu: Tüketim * Birim Maliyet -> Minimum yap
    prob += consumption_var * actual_cost
    prob.solve(PULP_CBC_CMD(msg=0))
    # --- DÜZELTME BURADA ---
    # PuLP çözüm üretemezse fallback (yedeğe) çekiyoruz
    optimized_load = value(consumption_var)
    # Çözüm bulunamazsa (None gelirse) optimized_load'u predicted_load'a eşitle
    if optimized_load is None:
        optimized_load = float(predicted_load)
    # Artık 'float - float' garantilendi
    reduction_amount = float(predicted_load) - float(optimized_load)
    savings = (reduction_amount * actual_cost) / 1000
    
    return {
        "load": round(predicted_load, 2),
        "target_load": round(optimized_load, 2),
        "reduction": round(reduction_amount, 2),
        "savings": round(savings, 2),
        "action": "YÜK KAYDIR" if is_critical or ptf > 2500 else "NORMAL",
        "recommendation": "AGRESİF KISINTI" if is_critical else "STANDART OPTİMİZASYON",
        "market_status": "ENERJİ AÇIĞI" if is_critical else "STABİL"
    }

def summarize_vpp_results(hourly_details: list):
    """
    Dashboard özet verilerini toplar.
    """
    if not hourly_details:
        return {"total_savings_tl": 0,"avg_savings_tl": 0, "total_reduction_kwh": 0,"avg_reduction_kwh": 0, "total_load_kwh": 0, "avg_ptf": 0}

    return {
        "total_savings_tl": round(sum(d.get('savings', 0) for d in hourly_details), 2),
        "avg_savings_tl": round(np.mean([d.get('savings', 0) for d in hourly_details]), 2) if hourly_details else 0,
        "total_reduction_kwh": round(sum(d.get('reduction', 0) for d in hourly_details), 2),
        "avg_reduction_kwh": round(np.mean([d.get('reduction', 0) for d in hourly_details]), 2) if hourly_details else 0,
        "total_load_kwh": round(sum(d.get('load', 0) for d in hourly_details), 2),
        "avg_ptf": round(np.mean([d.get('ptf', 0) for d in hourly_details]), 2) if hourly_details else 0
    }