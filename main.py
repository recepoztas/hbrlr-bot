import os
import time
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

# Kategorilerine göre zenginleştirilmiş RSS kaynakları
RSS_FEEDS = [
    # Gündem
    {"url": "https://www.trthaber.com/sondakika_articles.rss", "kategori": "Gündem"},
    {"url": "https://www.cnnturk.com/feed/rss/all/news", "kategori": "Gündem"},
    
    # Spor
    {"url": "https://www.fotomac.com.tr/rss/anasayfa.xml", "kategori": "Spor"},
    {"url": "https://www.fanatik.com.tr/rss/anasayfa", "kategori": "Spor"},
    {"url": "https://www.ntvspor.net/rss/anasayfa", "kategori": "Spor"},

    # Ekonomi
    {"url": "https://www.bloomberght.com/rss", "kategori": "Ekonomi"},

    # Teknoloji
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
    Aşağıdaki haberi incele.

    GENEL KURAL (Haberlerin %80-90'ı için):
    - BAŞLIK: İlgi çekici, merak uyandıran, modern ve kısa bir başlık at (4-7 kelime). Zorlama sorular sorma.
    - ÖZET: Haberin en kritik sonucunu veya detayını veren ultra kısa bir özet yaz (Maksimum 3-4 kelime).

    İSTİSNA KURAL (Sadece tam uyan eğlenceli/spesifik haberlerde - Çok nadir kullan):
    - Eğer haber çok net bir Evet/Hayır merakı doğuruyorsa (Örn: "Maaşlara zam geldi mi?", "Derbi ertelendi mi?"):
      * BAŞLIK: Net bir soru cümlesi yap.
      * ÖZET: Sadece "Evet" ya da "Hayır" yaz.

    ÇIKTI FORMATI:
    Aynen şu formatta ver, ekstra açıklama ekleme:
    BAŞLIK: [Başlık]
    ÖZET: [Özet]

    Haber Başlığı: {orijinal_baslik}
    Haber İçeriği: {metin}
    """
    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=prompt
        )
        cikti = response.text.strip()
        
        yeni_baslik = orijinal_baslik
        ozet = ""

        for satir in cikti.split("\n"):
            if satir.startswith("BAŞLIK:"):
                yeni_baslik = satir.replace("BAŞLIK:", "").strip()
            elif satir.startswith("ÖZET:"):
                ozet = satir.replace("ÖZET:", "").strip()

        if not ozet:
            ozet = cikti

        return yeni_baslik, ozet
    except Exception as e:
        print("AI Hatası:", e)
        return orijinal_baslik, None

def main():
    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        kategori = feed_info["kategori"]
        
        feed = feedparser.parse(feed_url)
        # Her kaynaktan en güncel 2 haberi çekelim
        for entry in feed.entries[:2]:
            orijinal_baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            # Veritabanında aynı haberin olup olmadığını kontrol et
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

