import os
import time
import json
import requests
import feedparser
from google import genai
from google.genai import types
from supabase import create_client, Client

# Ortam değişkenleri
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

RSS_FEEDS = [
    {"url": "https://www.trthaber.com/sondakika_articles.rss", "kategori": "Gündem"},
    {"url": "https://www.cnnturk.com/feed/rss/all/news", "kategori": "Gündem"},
    {"url": "https://www.fotomac.com.tr/rss/anasayfa.xml", "kategori": "Spor"},
    {"url": "https://www.fanatik.com.tr/rss/anasayfa", "kategori": "Spor"},
    {"url": "https://www.bloomberght.com/rss", "kategori": "Ekonomi"},
    {"url": "https://www.donanimhaber.com/rss/tum/", "kategori": "Teknoloji"}
]

DEFAULT_IMAGE = "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800"

def resim_url_al(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get('url', DEFAULT_IMAGE)
    if 'enclosures' in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href', DEFAULT_IMAGE)
    return DEFAULT_IMAGE

def haberi_islemden_gecir(metin, orijinal_baslik, kategori, yayin_tarihi):
    prompt = f"""
    Sen minimalist ve doğal bir dille haber özetleyen anti-clickbait editörüsün.

    YAYIN TARİHİ: {yayin_tarihi}

    ÖNEMLİ KURAL 1 - ÖZNE VE ÖZEL İSİM ZORUNLULUĞU (ÇOK KRİTİK):
    - Başlık "Kim elendi?", "Kim kazandı?", "Kimi transfer etti?", "Sakatlandı mı?" gibi spesifik bir kişi/kurum soruyorsa; özet MUTLAKA o kişinin veya kurumun ÖZEL İSMİNİ barındırmalıdır.
    - Eğer haber içeriğinde elenen/kazanan/bahsedilen kişinin İSMİ AÇIKÇA YAZMIYORSA (sadece "yarışmaya veda etti", "belli oldu" gibi muğlak laflar varsa) ozet alanına SADECE "YETERSIZ" yaz.
    - YANLIŞ ÖRNEK: Başlık: "MasterChef'te kim elendi?" -> Özet: "Yarışmaya veda etti." (İsim yok, GEÇERSİZ)
    - DOĞRU ÖRNEK: Başlık: "MasterChef'te kim elendi?" -> Özet: "Ayşe yarışmaya veda etti."

    ÖNEMLİ KURAL 2 - TARİH / SAAT BİLGİSİ VE BEYANLAR:
    - Haber metninde net bir tarih, gün veya saat bilgisi geçiyorsa (örn: "9 Eylül Çarşamba TSİ 21.00"), bu bilgiyi özet olarak yaz.
    - Metin içinde "netleşmedi" gibi ifadeler geçse bile, eğer metnin devamında saat/tarih veriliyorsa O BİLGİYİ AL.
    - YALNIZCA haber içeriğinde GERÇEKTEN hiçbir saat/tarih/isim veya somut yanıt yoksa ozet alanına SADECE "YETERSIZ" yaz.

    ÖNEMLİ KURAL 3 - ÖZET FORMATI (2-5 KELİME):
    - Özet, başlığa verilen Ultra Net, Özel İsim / Somut Bilgi İçeren doğrudan bir cevap olmalıdır.

    ÖNEMLİ KURAL 4 - BAĞLAMSAL VE DOĞAL BAŞLIKLAR:
    - Soruları okuyucunun konuyu anlayacağı DOĞAL ve BAĞLAMSAL bir dille sor.
    - YANLIŞ: "Onuachu maça devam edebildi mi?"
    - DOĞRU: "Onuachu sakatlandı mı?"

    Haber Başlığı: {orijinal_baslik}
    Haber İçeriği: {metin}
    """

    try:
        # Seçilen model: gemini-3.5-flash
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "OBJECT",
                    "properties": {
                        "baslik": {"type": "STRING"},
                        "ozet": {"type": "STRING"}
                    },
                    "required": ["baslik", "ozet"]
                }
            )
        )
        
        data = json.loads(response.text.strip())
        return data.get("baslik", orijinal_baslik), data.get("ozet", "")
        
    except Exception as e:
        print("AI Hatası:", e)
        return orijinal_baslik, None

def main():
    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        kategori = feed_info["kategori"]
        
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:3]:
            orijinal_baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            # RSS'ten yayın tarihini al
            yayin_tarihi = entry.get("published", entry.get("updated", "Tarih Belirtilmedi"))

            # 1. Birebir Link Kontrolü
            check_link = supabase.table("haberler").select("id").eq("link", link).execute()
            if len(check_link.data) > 0:
                continue

            # 2. AI İşlemi
            yeni_baslik, ozet = haberi_islemden_gecir(
                entry.get("summary", orijinal_baslik), 
                orijinal_baslik, 
                kategori, 
                yayin_tarihi
            )
            
            # İçerik yetersizse, isim barındırmıyorsa veya AI "YETERSIZ" dediyse doğrudan atla
            if not ozet or "YETERSIZ" in ozet.upper() or len(ozet) <= 2:
                print(f"Atlandı (Eksik İsim/İçerik): {orijinal_baslik}")
                continue

            # 3. AI Başlığı Üzerinden Mükerrer Kontrolü
            check_title = supabase.table("haberler").select("id").ilike("baslik", f"%{yeni_baslik}%").execute()
            if len(check_title.data) > 0:
                print(f"Tekrar Eden Haber Atlandı: {yeni_baslik}")
                continue

            # Veritabanına Ekleme
            data = {
                "baslik": yeni_baslik,
                "ozet": ozet,
                "link": link,
                "resim_url": resim_url,
                "kategori": kategori
            }
            supabase.table("haberler").insert(data).execute()
            print(f"Eklendi ({kategori}):\n  Başlık: {yeni_baslik}\n  Özet: {ozet}\n")
                
            time.sleep(2)

if __name__ == "__main__":
    main()


