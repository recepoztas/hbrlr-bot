import os
import time
import json
import random
import requests
import feedparser
from bs4 import BeautifulSoup
from groq import Groq
from supabase import create_client, Client

# ====================== ORTAM DEĞİŞKENLERİ ======================
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = Groq(api_key=GROQ_API_KEY)

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
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

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
                for tag in element(["script", "style", "aside", "nav", "footer", "iframe"]):
                    tag.decompose()
                text = element.get_text(separator=" ", strip=True)
                if len(text) > 150:
                    return text[:4000]

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

Sadece aşağıdaki JSON formatında cevap ver, başka hiçbir şey yazma:
{{
  "baslik": "...",
  "ozet": "..."
}}
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "system", "content": "Sen sadece istenen JSON formatında cevap veren bir haber editörüsün."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=250,
                response_format={"type": "json_object"}
            )

            raw = completion.choices[0].message.content.strip()
            if not raw:
                print(f"  → AI boş cevap döndü (Deneme {attempt+1})")
                time.sleep(5)
                continue

            data = json.loads(raw)
            return data.get("baslik", orijinal_baslik), data.get("ozet", "")

        except Exception as e:
            err_msg = str(e)
            if "rate_limit" in err_msg.lower() or "429" in err_msg:
                bekleme = 20 + (attempt * 15)
                print(f"  → Rate limit. {bekleme} saniye bekleniyor... (Deneme {attempt+1}/{max_retries})")
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

        for entry in feed.entries[:5]:  # Her kaynaktan 5 haber
            orijinal_baslik = entry.title.strip()
            link = entry.link
            resim_url = resim_url_al(entry)
            yayin_tarihi = entry.get("published", entry.get("updated", "Tarih Belirtilmedi"))

            # Link kontrolü
            try:
                check = supabase.table("haberler").select("id").eq("link", link).execute()
                if check.data:
                    continue
            except Exception as e:
                print(f"Supabase kontrol hatası: {e}")
                continue

            print(f"\nİşleniyor: {orijinal_baslik[:70]}...")

            rss_metin = entry.get("summary", "") or entry.get("description", "")
            if len(rss_metin) < 80:
                rss_metin = orijinal_baslik

            sayfa_metni = haber_sayfasindan_icerik_cek(link)
            
            if len(sayfa_metni) > len(rss_metin) + 100:
                icerik = sayfa_metni
                print("  → Sayfa içeriği kullanıldı")
            else:
                icerik = rss_metin
                print("  → RSS özeti kullanıldı")

            yeni_baslik, ozet = haberi_islemden_gecir(
                icerik, orijinal_baslik, kategori, yayin_tarihi
            )

            if not ozet or "YETERSIZ" in ozet.upper() or len(ozet.strip()) < 2:
                print(f"  → Atlandı (Yetersiz / Yerel): {orijinal_baslik[:60]}")
                continue

            try:
                check_title = supabase.table("haberler").select("id").ilike("baslik", f"%{yeni_baslik[:40]}%").execute()
                if check_title.data:
                    print(f"  → Tekrar eden başlık atlandı: {yeni_baslik}")
                    continue
            except:
                pass

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

            time.sleep(random.uniform(4, 7))

    print("\n\nTüm işlemler tamamlandı.")


if __name__ == "__main__":
    main()
