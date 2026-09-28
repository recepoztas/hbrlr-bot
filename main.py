import os
import time
import json
import random
import requests
import feedparser
from bs4 import BeautifulSoup
from groq import Groq
from supabase import create_client, Client
from datetime import datetime

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
    {"url": "https://www.halktv.com.tr/rss", "kategori": "Gündem"},
    {"url": "https://www.sporx.com/_xml/rss.php", "kategori": "Spor"},
    {"url": "https://www.bloomberght.com/rss", "kategori": "Ekonomi"},
    {"url": "https://www.donanimhaber.com/rss/tum/", "kategori": "Teknoloji"},
]

DEFAULT_IMAGE = "https://images.unsplash.com/photo-1504711434969-e33886168f5c?q=80&w=800"
BURC_IMAGE = "https://images.unsplash.com/photo-1532968967656-8c4c0b0a0b0b?q=80&w=800"

# DEĞİŞTİRİLEN MODEL: Türkçe gazetecilik kalitesi için daha güçlü model
GROQ_MODEL = "llama-3.3-70b-versatile"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

BURCLAR = ["Koç", "Boğa", "İkizler", "Yengeç", "Aslan", "Başak", "Terazi", "Akrep", "Yay", "Oğlak", "Kova", "Balık"]

# ====================== YARDIMCI FONKSİYONLAR ======================
def rss_ten_resim_al(entry):
    """1. kaynak: RSS içindeki görsel alanları"""
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url")
    if "enclosures" in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href")
    return None


def sayfa_detay_cek(url: str):
    """YENİ: Hem metni hem og:image görselini tek seferde çeker.
    Dönen değer: (metin, resim_url)"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # --- Görsel: og:image meta etiketinden al ---
        resim_url = None
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og and og.get("content"):
            resim_url = og["content"]
            if resim_url.startswith("/"):  # eksik domain tamamla
                from urllib.parse import urljoin
                resim_url = urljoin(url, resim_url)

        # --- Metin: makale gövdesini bul ---
        selectors = [
            "article", ".news-content", ".haber-metni", ".detail-content",
            ".content-body", ".story-body", ".article-body",
            "#news-content", ".post-content", "div[itemprop='articleBody']",
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                for tag in element(["script", "style", "aside", "nav", "footer", "iframe"]):
                    tag.decompose()
                text = element.get_text(separator=" ", strip=True)
                if len(text) > 150:
                    return text[:4000], resim_url

        body = soup.find("body")
        if body:
            for tag in body(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = body.get_text(separator=" ", strip=True)
            return text[:3500], resim_url

    except Exception as e:
        print(f"  → Sayfa çekilemedi ({url[:60]}...): {e}")

    return "", None


def haberi_islemden_gecir(metin: str, orijinal_baslik: str, kategori: str, yayin_tarihi: str):
    prompt = f"""
Sen Türkiye'nin önde gelen haber sitelerinde çalışan, deneyimli bir haber editörüsün.
Kaynaktaki ham haberi okuyup sitede yayınlanacak hâle getiriyorsun.

YAYIN TARİHİ: {yayin_tarihi}
KATEGORİ: {kategori}

### KURALLAR

1. BAŞLIK
   - 8-12 kelime, akıcı ve doğal Türkçe.
   - "flaş", "bomba", "şok", "sürpriz", "son dakika" gibi abartılı kelimeleri ASLA kullanma.
   - Her haberi soru cümlesi yapma; düz ve net anlat.

2. ÖZET (en kritik kural)
   - 15-20 kelime, tek paragraf.
   - Başlığın tekrarı olmasın; başlıkta olmayan somut bilgiyi ver
     (kim, ne, ne zaman, rakam, sonuç).
   - Doğal gazetecilik dili kullan; çeviri kokan, robot gibi cümleler kurma.
   - Örnek doğru cümle: "Fenerbahçe, sözleşmesi bitecek oyuncuyla yeniden masaya oturacak."
   - Ek bilgi çıkaramıyorsan "YETERSIZ" yaz.

3. ÖZEL DURUMLAR
   - Maç varsa saat/kanal, deprem varsa büyüklük, transfer varsa kesin bilgi yoksa "Transfer yok".

Haber Başlığı: {orijinal_baslik}
Haber İçeriği: {metin}

SADECE şu JSON formatında cevap ver:
{{
  "baslik": "...",
  "ozet": "..."
}}
"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "Sen deneyimli bir Türk haber editörüsün. Cevabın HER ZAMAN geçerli JSON formatında olur. Türkçe gazetecilik dilini kullanırsın: kısa, net, doğal ve çeviri kokmayan cümleler. Abartılı kelimeler kullanmazsın. Başlık ve özet birbirinden farklı olur; özet daha somut bilgi içerir."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                max_tokens=350
            )

            raw = completion.choices[0].message.content.strip()

            if not raw:
                print(f"  → AI boş cevap döndü (Deneme {attempt+1})")
                time.sleep(4)
                continue

            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                raw = raw[start:end]

            data = json.loads(raw)
            return data.get("baslik", orijinal_baslik), data.get("ozet", "")

        except Exception as e:
            err_msg = str(e)
            if "rate_limit" in err_msg.lower() or "429" in err_msg:
                bekleme = 12 + (attempt * 8)
                print(f"  → Rate limit. {bekleme} saniye bekleniyor... (Deneme {attempt+1}/{max_retries})")
                time.sleep(bekleme)
            else:
                print(f"  → AI Hatası ({orijinal_baslik[:40]}...): {e}")
                time.sleep(3)
                continue

    return orijinal_baslik, None


def burc_yorumu_uret(burc_adi: str):
    prompt = f"""
Sen profesyonel bir astrologsun. {burc_adi} burcu için bu haftanın yorumunu yaz.

Kurallar:
- Çok kısa ama kapsamlı olsun (maksimum 12-14 kelime).
- Aşk, iş/para ve genel enerjiyi tek cümlede özetle.
- Abartısız, net ve anlaşılır olsun.
- Sadece Türkçe yaz.

Örnek format:
"Aşkta netlik arayışı, işte yeni fırsatlar, enerji yüksek tutun."

Sadece yorumu yaz, başka hiçbir şey ekleme.
"""

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "Sen kısa, net ve kaliteli haftalık burç yorumu yazan bir astrologsun."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4,
            max_tokens=100
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"  → Burç yorumu hatası ({burc_adi}): {e}")
        return None


def haftalik_burc_yorumlarini_cek():
    bugun = datetime.now()
    if bugun.weekday() != 0:  # 0 = Pazartesi
        print("Bugün Pazartesi değil, burç yorumları atlandı.")
        return

    print("\n=== HAFTALIK BURÇ YORUMLARI GÜNCELLENİYOR ===")

    try:
        supabase.table("haberler").delete().eq("kategori", "Burç").execute()
        print("  → Eski burç yorumları silindi")
    except Exception as e:
        print(f"  → Eski burçları silerken hata: {e}")

    for burc in BURCLAR:
        print(f"İşleniyor: {burc}...")
        ozet = burc_yorumu_uret(burc)

        if not ozet or len(ozet) < 10:
            print(f"  → {burc} yorumu üretilemedi")
            continue

        data = {
            "baslik": f"{burc} Burcu Haftalık Yorum",
            "ozet": ozet,
            "link": "https://www.milliyet.com.tr/pembenar/haftalik-burc-yorumlari/",
            "resim_url": BURC_IMAGE,
            "kategori": "Burç"
        }

        try:
            supabase.table("haberler").insert(data).execute()
            print(f"  ✓ Eklendi → {burc}: {ozet}")
        except Exception as e:
            print(f"  → Kayıt hatası ({burc}): {e}")

        time.sleep(random.uniform(3, 5))

    print("=== BURÇ YORUMLARI GÜNCELLENDİ ===\n")


# ====================== ANA FONKSİYON ======================
def main():
    print("Haber toplama işlemi başladı...\n")

    haftalik_burc_yorumlarini_cek()

    for feed_info in RSS_FEEDS:
        feed_url = feed_info["url"]
        kategori = feed_info["kategori"]
        print(f"\n=== {kategori.upper()} → {feed_url} ===")

        try:
            feed = feedparser.parse(feed_url)
        except Exception as e:
            print(f"RSS okunamadı: {e}")
            continue

        for entry in feed.entries[:5]:
            orijinal_baslik = entry.title.strip()
            link = entry.link

            try:
                check = supabase.table("haberler").select("id").eq("link", link).execute()
                if check.data:
                    continue
            except Exception as e:
                print(f"Supabase kontrol hatası: {e}")
                continue

            print(f"\nİşleniyor: {orijinal_baslik[:70]}...")

            # 1. önce RSS'ten görsel dene
            resim_url = rss_ten_resim_al(entry)

            # 2. sayfayı çek: metin + og:image
            sayfa_metni, sayfa_resmi = sayfa_detay_cek(link)

            # 3. görsel hâlâ yoksa og:image'i kullan
            if not resim_url and sayfa_resmi:
                resim_url = sayfa_resmi
                print("  → Görsel sayfadaki og:image'den alındı")

            # 4. hiçbiri yoksa yedek görsel
            if not resim_url:
                resim_url = DEFAULT_IMAGE
                print("  → Görsel bulunamadı, yedek kullanıldı")

            yayin_tarihi = entry.get("published", entry.get("updated", "Tarih Belirtilmedi"))

            rss_metin = entry.get("summary", "") or entry.get("description", "")
            if len(rss_metin) < 80:
                rss_metin = orijinal_baslik

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

