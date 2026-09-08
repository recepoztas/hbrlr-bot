import os
import time
import json
import random
import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from supabase import create_client, Client

# ====================== ORTAM DEĞİŞKENLERİ ======================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)

# ====================== RSS KAYNAKLARI ======================
RSS_FEEDS = [
    {"url": "https://www.trthaber.com/sondakika_articles.rss", "kategori": "Gündem"},
    {"url": "https://www.cnnturk.com/feed/rss/all/news", "kategori": "Gündem"},
    {"url": "https://www.fotomac.com.tr/rss/anasayfa.xml", "kategori": "Spor"},
    {"url": "https://www.fanatik.com.tr/rss/anasayfa", "kategori": "Spor"},
    {"url": "https://www.bloomberght.com/rss", "kategori": "Ekonomi"},
    {"url": "https://www.donanimhaber.com/rss/tum/", "kategori": "Teknoloji"},
]

DEFAULT_IMAGE = "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ====================== YARDIMCI FONKSİYONLAR ======================
def resim_url_al(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url", DEFAULT_IMAGE)
    if "enclosures" in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href", DEFAULT_IMAGE)
    return DEFAULT_IMAGE


def haber_sayfasindan_icerik_cek(url: str) -> str:
    """Haber sayfasının ana metnini çekmeye çalışır."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # Yaygın haber sitelerinin ana içerik alanlarını dene
        selectors = [
            "article",
            ".news-content",
            ".haber-metni",
            ".detail-content",
            ".content-body",
            ".story-body",
            ".article-body",
            "#news-content",
            ".post-content",
            "div[itemprop='articleBody']",
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                # Gereksiz etiketleri temizle
                for tag in element(["script", "style", "aside", "nav", "footer", "iframe"]):
                    tag.decompose()
                text = element.get_text(separator=" ", strip=True)
                if len(text) > 150:
                    return text[:4000]  # Gemini'ye çok uzun göndermemek için

        # Hiçbiri tutmazsa body'den al
        body = soup.find("body")
        if body:
            for tag in body(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = body.get_text(separator=" ", strip=True)
            return text[:3500]

    except Exception as e:
        print(f"  → Sayfa çekilemedi ({url[:60]}...): {e}")
    
    return ""


def haberi_islemden_gecir(metin: str, orijinal_baslik: str, kategori: str, yayin_tarihi: str):
    prompt = f"""
Sen Türkiye'deki haberleri en kısa, net ve aranabilir soru-cevap formatına çeviren profesyonel bir editörsün.

YAYIN TARİHİ: {yayin_tarihi}
KATEGORİ: {kategori}

### ANA AMAÇ
Kullanıcı Google'da ne ararsa o soruyu başlık yap, cevabı ise mümkün olan en kısa ve doğru şekilde ver.

### ÖNCELİK SIRASI

1. MAÇ / SPOR YAYIN BİLGİLERİ (EN ÖNEMLİ)
   - Saat ve kanal bilgisi varsa mutlaka çıkar.
   - Format örnekleri:
     • "9 Eylül Çarşamba 22:00 / TRT 1"
     • "22:00 / beIN Sports"
     • "Galatasaray 2-1 kazandı"
   - Bilgi eksik olsa bile en net cevabı ver, "YETERSIZ" deme.

2. DİĞER HABERLER
   - Ülkeyi ilgilendiren, insanların arayabileceği her haberi işle (ekonomi, zam, teknoloji, önemli yerel olaylar dahil).
   - Sadece gerçekten çok önemsiz ve yerel (örneğin mahalle yangını, küçük trafik kazası) haberlerde ozet alanına "YETERSIZ" yaz.

3. ÖZET KURALLARI
   - Maksimum 12 kelime.
   - Doğrudan cevap olsun. Gereksiz giriş cümlesi ekleme.
   - Örnekler: "22:00 / TRT 1", "Dolar 34.85 TL", "Zam yok", "Galatasaray şampiyon oldu"

4. BAŞLIK KURALLARI
   - Doğal arama dili kullan.
   - Örnek: "Galatasaray - Real Madrid maçı ne zaman, hangi kanalda?"
   - Örnek: "Benzine zam geldi mi?"
   - Uydurma veya abartılı soru yazma.

Haber Başlığı: {orijinal_baslik}
Haber İçeriği: {metin}
"""

    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
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
                    },
                    temperature=0.25,
                    max_output_tokens=200
                )
            )

            data = json.loads(response.text.strip())
            return data.get("baslik", orijinal_baslik), data.get("ozet", "")

        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                bekleme = 40 + (attempt * 15)
                print(f"  → Kota aşıldı (429). {bekleme} saniye bekleniyor... (Deneme {attempt+1}/{max_retries})")
                time.sleep(bekleme)
            else:
                print(f"  → AI Hatası ({orijinal_baslik[:40]}...): {e}")
                return orijinal_baslik, None

    return orijinal_baslik, None


# ====================== ANA FONKSİYON ======================
def main():
    print("Haber toplama işlemi başladı...\n")

    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        kategori = feed_info["kategori"]
        print(f"\n=== {kategori.upper()} → {feed_url} ===")

        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"RSS okunamadı: {e}")
            continue

        for entry in feed.entries[:12]:  # Her kaynaktan son 12 haber
            orijinal_baslik = entry.title.strip()
            link = entry.link
            resim_url = resim_url_al(entry)
            yayin_tarihi = entry.get("published", entry.get("updated", "Tarih Belirtilmedi"))

            # 1. Link zaten var mı?
            try:
                check = supabase.table("haberler").select("id").eq("link", link).execute()
                if check.data:
                    continue
            except Exception as e:
                print(f"Supabase kontrol hatası: {e}")
                continue

            print(f"\nİşleniyor: {orijinal_baslik[:70]}...")

            # 2. Önce RSS özetini al
            rss_metin = entry.get("summary", "") or entry.get("description", "")
            if len(rss_metin) < 80:
                rss_metin = orijinal_baslik

            # 3. Haber sayfasından da içerik çek
            sayfa_metni = haber_sayfasindan_icerik_cek(link)
            
            # En iyi metni seç
            if len(sayfa_metni) > len(rss_metin) + 100:
                icerik = sayfa_metni
                print("  → Sayfa içeriği kullanıldı")
            else:
                icerik = rss_metin
                print("  → RSS özeti kullanıldı")

            # 4. AI ile işle
            yeni_baslik, ozet = haberi_islemden_gecir(
                icerik,
                orijinal_baslik,
                kategori,
                yayin_tarihi
            )

            # 5. Filtre
            if not ozet or "YETERSIZ" in ozet.upper() or len(ozet.strip()) < 2:
                print(f"  → Atlandı (Yetersiz / Yerel): {orijinal_baslik[:60]}")
                continue

            # 6. Başlık tekrarı kontrolü
            try:
                check_title = supabase.table("haberler").select("id").ilike("baslik", f"%{yeni_baslik[:40]}%").execute()
                if check_title.data:
                    print(f"  → Tekrar eden başlık atlandı: {yeni_baslik}")
                    continue
            except:
                pass

            # 7. Veritabanına ekle
            data = {
                "baslik": yeni_baslik,
                "ozet": ozet,
                "link": link,
                "resim_url": resim_url,
                "kategori": kategori
            }

            try:
                supabase.table("haberler").insert(data).execute()
                print(f"  ✓ Eklendi → Başlık: {yeni_baslik}")
                print(f"             Özet  : {ozet}")
            except Exception as e:
                print(f"  → Veritabanı ekleme hatası: {e}")

            # Kota dostu bekleme
            time.sleep(random.uniform(3.5, 4.8))

    print("\n\nTüm işlemler tamamlandı.")


if __name__ == "__main__":
    main()
