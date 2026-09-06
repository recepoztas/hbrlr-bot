import os
import requests
import feedparser
import google.generativeai as genai
from supabase import create_client, Client

# Değişkenleri ortamdan çek
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# RSS haber kaynakları
RSS_FEEDS = [
    "https://www.trthaber.com/sondakika_articles.rss",
    "https://www.cnnturk.com/feed/rss/all/news"
]

DEFAULT_IMAGE = "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800"

def resim_url_al(entry):
    """RSS kaydından görsel URL'sini ayıklar."""
    # 1. 'media_content' kontrolü
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get('url', DEFAULT_IMAGE)
    # 2. 'enclosures' kontrolü
    if 'enclosures' in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href', DEFAULT_IMAGE)
    # 3. Bulunamazsa varsayılan haber görselini dön
    return DEFAULT_IMAGE

def haberi_ozetle(metin, baslik):
    prompt = f"""
    Sen net ve abartılı derecede kısa cevaplar veren bir haber editörüsün.
    Aşağıdaki haber başlığını ve metnini oku. 
    Bu habere veya soruya verilere dayanarak MÜMKÜN OLAN EN KISA cevabı ver. 
    Eğer soru "Edecek mi/Olacak mı" gibi bir soruysa cevabın sadece "Evet", "Hayır" veya "Belki" olabilir. 
    Diğer durumlarda cevap maksimum 1-3 kelimeyi geçmesin (Örn: "Zorunlu Oldu", "İptal Edildi", "15 Ekim'de").
    
    Haber Başlığı: {baslik}
    Haber Metni: {metin}
    
    Sadece cevabı yaz, başka hiçbir açıklama yapma:
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print("AI Hatası:", e)
        return None

def main():
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:3]:  # Her kaynaktan son 3 haber
            baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            # Veritabanında var mı kontrol et
            check = supabase.table("haberler").select("id").eq("link", link).execute()
            if len(check.data) == 0:
                ozet = haberi_ozetle(entry.get("summary", baslik), baslik)
                if ozet:
                    supabase.table("haberler").insert({
                        "baslik": baslik,
                        "ozet": ozet,
                        "link": link,
                        "resim_url": resim_url
                    }).execute()
                    print(f"Eklendi: {baslik} -> {ozet}")

if __name__ == "__main__":
    main()

