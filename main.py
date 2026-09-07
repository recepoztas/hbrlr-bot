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
    Sen minimalist, merak uyandıran soru-cevap formatında içerik üreten anti-clickbait bir haber editörüsün.

    YAYIN TARİHİ: {yayin_tarihi}
    KATEGORİ: {kategori}

    KRİTİK FİLTRE 1 - İLGİÇLİK VE ARANABİLİRLİK FİLTRESİ (ÇOK KRİTİK):
    - Sıradan asayiş olaylarını (yıldırım düşmesi, yerel kaza, münferit kavga/yangın vb.), sıradan yerel haberleri ELE.
    - SADECE insanların arama motorlarında aratacağı, genel kamuoyunun merak edeceği (Örn: Maç saatleri/kanalları, transferler, elenen isimler, ekonomi/zam kararları, teknoloji duyuruları) haberleri işle.
    - Eğer haber sıradan bir bölgesel olaysa veya aranacak bir nitelikte değilse ozet alanına SADECE "YETERSIZ" yaz.

    KRİTİK FİLTRE 2 - ÖZNE VE ÖZEL İSİM ZORUNLULUĞU:
    - Başlık veya soru bir kişi/kurum/saat/kanal soruyorsa; özet MUTLAKA o net bilgiyi (İsim, Saat, Yayın Kanalı vb.) içermelidir.
    - Metin içinde bu net cevap yoksa ozet alanına SADECE "YETERSIZ" yaz.

    ÖNEMLİ KURAL 3 - MAÇ VE ETKİNLİK HABERLERİ:
    - Maç haberlerinde "Hangi kanalda?", "Saat kaçta?" sorularının cevabı metinde varsa özete "9 Eylül Çarşamba TSİ 22.00 / TRT 1" gibi NET bilgi yaz.

    ÖNEMLİ KURAL 4 - ÖZET FORMATI (2-5 KELİME):
    - Özet, soruya verilen doğrudan ve en kısa cevap olmalıdır.

    ÖNEMLİ KURAL 5 - BAĞLAMSAL VE DOĞAL BAŞLIKLAR:
    - Soruyu okuyucunun aratacağı doğal bir dille yaz (Örn: "Galatasaray - Real Madrid maçı ne zaman, hangi kanalda?").

    Haber Başlığı: {orijinal_baslik}
    Haber İçeriği: {metin}
    """

    try:
        # İstenildiği gibi gemini-3.5-flash korundu
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
        print(f"AI Hatası ({orijinal_baslik[:20]}...):", e)
        return orijinal_baslik, None

def main():
    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        kategori = feed_info["kategori"]
        
        feed = feedparser.parse(feed_url)
        # Maç ve önemli haberleri kaçırmamak için tarama 3'ten 10'a çıkarıldı
        for entry in feed.entries[:10]:
            orijinal_baslik = entry.title
            link = entry.link
            resim_url = resim_url_al(entry)
            
            # İçeriğin boş kalmaması için daha geniş metin kontrolü
            icerik_metni = entry.get("summary", "")
            if "description" in entry and len(entry.description) > len(icerik_metni):
                icerik_metni = entry.description

            yayin_tarihi = entry.get("published", entry.get("updated", "Tarih Belirtilmedi"))

            # 1. Birebir Link Kontrolü
            check_link = supabase.table("haberler").select("id").eq("link", link).execute()
            if len(check_link.data) > 0:
                continue

            # 2. AI İşlemi
            yeni_baslik, ozet = haberi_islemden_gecir(
                icerik_metni if icerik_metni else orijinal_baslik, 
                orijinal_baslik, 
                kategori, 
                yayin_tarihi
            )
            
            # İçerik yetersizse, sıradan asayişse veya AI "YETERSIZ" dediyse doğrudan atla
            if not ozet or "YETERSIZ" in ozet.upper() or len(ozet) <= 2:
                print(f"Atlandı (Filtre/Yetersiz İçerik): {orijinal_baslik}")
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

