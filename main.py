import os
import time
import json
import requests
import feedparser
from google import genai
from google.genai import types
from supabase import create_client, Client

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

def haberi_islemden_gecir(metin, orijinal_baslik, kategori):
    prompt = f"""
    Sen mikro-haber formatında yayın yapan ultra minimalist bir editörsün.
    Görevin: Her haberi doğal bir "Soru - Kestirme Cevap" ikilisine dönüştürmek.

    TEMEL FORMAT ŞARTLARI:
    1. BAŞLIK:
       - Haberi okuyucunun merak edeceği DOĞAL bir soru cümlesine çevir.
       - Asla zorlama "Evet/Hayır" gerektiren yapay sorular sorma. 
       - "Ne dedi?", "Soru ne oldu?", "Kime ne oldu?", "Saat kaçta?", "Açıklandı mı?" gibi sorular kullan.

    2. ÖZET (ÇOK ÖNEMLİ):
       - Soruya verilecek cevabı MÜMKÜN OLAN EN KISA ŞEKİLDE yaz.
       - Cevap KESİNLİKLE 2-4 KELİMEYİ GEÇEMEZ!
       - Yanına bağlaç, açıklama, ek cümle ASLA ekleme.

    ÖRNEKLER:
    - Orijinal: "Cumhurbaşkanı Erdoğan Filenin Sultanlarını aradı."
      * baslik: "Erdoğan Filenin Sultanlarına ne dedi?"
      * ozet: "Tebrik etti."

    - Orijinal: "Daha 17 dizisinde Aras kardeşini arıyor."
      * baslik: "Aras kardeşini bulabildi mi?"
      * ozet: "Henüz değil."

    - Orijinal: "Trabzonspor Gençlerbirliği ile karşılaşacak."
      * baslik: "Trabzonspor maçı ne zaman, hangi kanalda?"
      * ozet: "Bugün 20:00 | TRT Spor"

    - Orijinal: "Merkez Bankası faiz kararını açıkladı."
      * baslik: "Merkez Bankası faizi ne yaptı?"
      * ozet: "Sabit tuttu."

    - Orijinal: "Asgari ücrete ara zam yapıldı."
      * baslik: "Asgari ücrete ne kadar zam geldi?"
      * ozet: "%30 zam yapıldı."

    Haber Başlığı: {orijinal_baslik}
    Haber İçeriği: {metin}
    """

    try:
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
        for entry in feed.entries[:3]:
            orijinal_baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            # 1. Link Kontrolü
            check_link = supabase.table("haberler").select("id").eq("link", link).execute()
            if len(check_link.data) > 0:
                continue

            # 2. Mükerrer Haber Kontrolü (Aynı haberin tekrar girmesini önler)
            kisa_baslik = orijinal_baslik[:18]
            check_title = supabase.table("haberler").select("id").ilike("baslik", f"%{kisa_baslik}%").execute()
            if len(check_title.data) > 0:
                continue

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
                
                time.sleep(2)

if __name__ == "__main__":
    main()

