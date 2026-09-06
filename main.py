
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
    {"url": "https://www.ntvspor.net/rss/anasayfa", "kategori": "Spor"},
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

def haberi_islemden_gecir(metin, orijinal_baslik, kategori):
    prompt = f"""
    Sen minimalist bir haber platformu için {kategori} kategorisinde editörlük yapıyorsun.
    Sana verilen haber başlığını ve detayını incele.

    KURAL 1 - MAÇ / MÜSABAKA HABERLERİ:
    - Eğer metinde maçın SAATİ veya YAYIN KANALI bilgisi varsa:
      * baslik: "Türkiye - İtalya maçı saat kaçta, hangi kanalda?"
      * ozet: Sadece saat ve kanal yaz (Örn: "Bugün 20:00 | TRT Spor")
    - Eğer saat veya kanal bilgisi metinde yoksa:
      * baslik: İlgi çekici kısa başlık (Örn: "Filenin Sultanları Dev Finalde")
      * ozet: En net durum özetini 3-5 kelimeyle yaz (Örn: "Türkiye ile İtalya şampiyonluk için karşılaşıyor.")

    KURAL 2 - GENEL HABERLER:
    - baslik: Merak uyandıran, net ve kısa bir başlık (4-7 kelime).
    - ozet: Haberin en kritik sonucunu veren ultra kısa detay (3-5 kelime).

    Haber Başlığı: {orijinal_baslik}
    Haber İçeriği: {metin}
    """

    try:
        # Yanıtın kesin olarak JSON formatında dönmesini sağlıyoruz
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
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
        for entry in feed.entries[:2]:
            orijinal_baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            check = supabase.table("haberler").select("id").eq("link", link).execute()
            if len(check.data) == 0:
                yeni_baslik, ozet = haberi_islemden_gecir(entry.get("summary", orijinal_baslik), orijinal_baslik, kategori)
                if ozet:
                    data = {
                        "baslik": yeni_baslik,
                        "ozet": ozet,
                        "link": link,
                        "resim_url": resim_url,
                        "kategori": kategori
                    }
                    supabase.table("haberler").insert(data).execute()
                    print(f"Eklendi ({kategori}):\n  Başlık: {yeni_baslik}\n  Özet: {ozet}\n")
                    
                    time.sleep(3)

if __name__ == "__main__":
    main()

