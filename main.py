import os
import requests
import feedparser
from google import genai
from supabase import create_client, Client

# Ortam değişkenleri
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# RSS haber kaynakları
RSS_FEEDS = [
    "https://www.trthaber.com/sondakika_articles.rss",
    "https://www.cnnturk.com/feed/rss/all/news"
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

def haberi_ozetle(metin, baslik):
    prompt = f"""
    Sen net ve kısa cevaplar veren bir haber editörüsün.
    Aşağıdaki haber başlığını ve metnini oku. 
    Bu habere veya soruya MÜMKÜN OLAN EN KISA cevabı ver (1-3 kelime).
    
    Haber Başlığı: {baslik}
    Haber Metni: {metin}
    
    Sadece cevabı yaz:
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print("AI Hatası:", e)
        return None

def main():
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:3]:
            baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            check = supabase.table("haberler").select("id").eq("link", link).execute()
            if len(check.data) == 0:
                ozet = haberi_ozetle(entry.get("summary", baslik), baslik)
                if ozet:
                    data = {
                        "baslik": baslik,
                        "ozet": ozet,
                        "link": link,
                        "resim_url": resim_url
                    }
                    supabase.table("haberler").insert(data).execute()
                    print(f"Eklendi: {baslik} -> {ozet}")

if __name__ == "__main__":
    main()

