code = r'''import os
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

# MODEL LİSTESİ: Yukarıdan aşağı denenir, biri çalışmayınca diğerine geçer.
# Böylece Groq bir modeli kaldırsa bile bot kendini kurtarır.
MODEL_LIST = [

    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

BURCLAR = ["Koç", "Boğa", "İkizler", "Yengeç", "Aslan", "Başak", "Terazi", "Akrep", "Yay", "Oğlak", "Kova", "Balık"]


def groq_istegi_gonder(messages, temperature, max_tokens, islem_adi=""):
    """Tüm modelleri sırayla dener. Hepsi başarısız olursa None döner."""
    for model in MODEL_LIST:
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            icerik = completion.choices[0].message.content
            if icerik and icerik.strip():
                return icerik.strip()
        except Exception as e:
            print(f" → {model} hatası ({islem_adi}): {str(e)[:120]}")
            time.sleep(3)
    print(f" → TÜM MODELLER BAŞARISIZ ({islem_adi})")
    return None


# ====================== YARDIMCI FONKSİYONLAR ======================
def rss_ten_resim_al(entry):
    if "media_content" in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get("url")
    if "enclosures" in entry and len(entry.enclosures) > 0:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image/"):
                return enc.get("href")
    return None


def sayfa_detay_cek(url: str):
    """Hem metni hem og:image görselini tek seferde çeker."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        resim_url = None
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og and og.get("content"):
            resim_url = og["content"]
            if resim_url.startswith("/"):
                from urllib.parse import urljoin
                resim_url = urljoin(url, resim_url)

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
        print(f" → Sayfa çekilemedi ({url[:60]}...): {e}")

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
   - "flaş", "bomba", "şok", "sürpriz", "son dakika" kelimelerini ASLA kullanma.
   - Her haberi soru cümlesi yapma; düz ve net anlat.

2. ÖZET (en kritik kural)
   - 18-25 kelime, tek paragraf.
   - BAĞLAM KURALI: Özeti, haberi HİÇ bilmeyen bir okuyucu için yaz.
     İsim geçen kişi, takım veya olay ilk kez anılıyorsa, cümle içinde
     kısaca kim/ney olduğunu açıkla.
     DOĞRU: "Milan'ın efsane kaptanı Baresi'nin duvar resmine yapılan saldırıyı
              eski kaleci Zenga kınadı."
     YANLIŞ: "Baresi'nin duvar resmine saldırıya Zenga tepki verdi."
     (Baresi'nin kim olduğunu bilmeyen okuyucu anlayamaz.)
   - ASLA başlığın farklı söylenmiş hâlini yazma. Özet yeni, somut bilgi içersin.
     DOĞRU: "Fenerbahçe, sözleşmesi bitecek olan oyuncunun satın alma
              opsiyonunu devreye sokacak."
     YANLIŞ: "Fenerbahçe transfer opsiyonunu kullanarak yeni oyuncu alacak."
     (Bu, başlığın tekrarıdır; bilgi sıfır.)
   - Grup içi hatalar olmasın: "pompala tüfekle", "polis eline geçince" gibi
     bozuk cümleler kurma. Anadili gibi doğru Türkçe yaz.
   - Ek bilgi çıkaramıyorsan "YETERSIZ" yaz.

3. ÖZEL DURUMLAR
   - Maç varsa saat/kanal, deprem varsa büyüklük.
   - TRANSFER: Özette oyuncu ADI ve takım ADI geçmeli. Kesin bilgi yoksa YETERSIZ.

Haber Başlığı: {orijinal_baslik}
Haber İçeriği: {metin}

SADECE şu JSON formatında cevap ver:
{{
  "baslik": "...",
  "ozet": "..."
}}
"""

    system_msg = {
        "role": "system",
        "content": ("Sen deneyimli bir Türk haber editörüsün. Cevabın HER ZAMAN geçerli JSON formatında olur. "
                    "Özetin; haberi hiç bilmeyen biri tarafından anlaşılabilir olması şarttır: geçen isimlerin "
                    "kim olduğu cümle içinde kısaca belli olur. Özet asla başlığın tekrarı olmaz, daima yeni somut "
                    "bilgi taşır. Ana dilindeki gibi doğru, akıcı Türkçe kullanırsın. Abartılı kelimeler kullanmazsın.")
    }

    for deneme in range(3):
        raw = groq_istegi_gonder(
            [system_msg, {"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=350, islem_adi=f"özet: {orijinal_baslik[:40]}"
        )
        if raw is None:
            return orijinal_baslik, None

        try:
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
            print(f" → JSON çözümlenemedi, tekrar deneniyor: {e}")
            time.sleep(3)

    return orijinal_baslik, None


def burc_yorumu_uret(burc_adi: str):
    prompt = f"""
Sen profesyonel bir astrologsun. {burc_adi} burcu için bu haftanın yorumunu yaz.

Kurallar:
- Çok kısa ama kapsamlı olsun (maksimum 12-14 kelime).
- Aşk, iş/para ve genel enerjiyi tek cümlede özetle.
- Abartısız, net ve anlaşılır olsun.
- Sadece Türkçe yaz.

Sadece yorumu yaz, başka hiçbir şey ekleme.
"""
    return groq_istegi_gonder(
        [
            {"role": "system", "content": "Sen kısa, net ve kaliteli haftalık burç yorumu yazan bir astrologsun."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4, max_tokens=100, islem_adi=f"burç: {burc_adi}"
    )


def haftalik_burc_yorumlarini_cek():
    bugun = datetime.now()
    pazartesi_mi = (bugun.weekday() == 0)

    # Veritabanında burç yorumu var mı kontrol et
    burc_var_mi = False
    try:
        mevcut = supabase.table("haberler").select("id").eq("kategori", "Burç").limit(1).execute()
        burc_var_mi = len(mevcut.data) > 0
    except Exception as e:
        print(f"Burç kontrol hatası: {e}")
        burc_var_mi = True # emin olamazsak mevcut olanı korumak için

    if not pazartesi_mi and burc_var_mi:
        print("Burç yorumları zaten mevcut, atlandı.")
        return

    if not burc_var_mi:
        print("Veritabanında burç yorumu yok, hemen üretiliyor...")
    else:
        print("Pazartesi: burç yorumları yenileniyor...")

    print("\n=== HAFTALIK BURÇ YORUMLARI GÜNCELLENİYOR ===")

    if burc_var_mi:
        try:
            supabase.table("haberler").delete().eq("kategori", "Burç").execute()
            print(" → Eski burç yorumları silindi")
        except Exception as e:
            print(f" → Eski burçları silerken hata: {e}")

    for burc in BURCLAR:
        print(f"İşleniyor: {burc}...")
        ozet = burc_yorumu_uret(burc)

        if not ozet or len(ozet) < 10:
            print(f" → {burc} yorumu üretilemedi")
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
            print(f" ✓ Eklendi → {burc}: {ozet}")
        except Exception as e:
            print(f" → Kayıt hatası ({burc}): {e}")

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

            resim_url = rss_ten_resim_al(entry)
            sayfa_metni, sayfa_resmi = sayfa_detay_cek(link)

            if not resim_url and sayfa_resmi:
                resim_url = sayfa_resmi
                print(" → Görsel sayfadaki og:image'den alındı")
            if not resim_url:
                resim_url = DEFAULT_IMAGE
                print(" → Görsel bulunamadı, yedek kullanıldı")

            yayin_tarihi = entry.get("published", entry.get("updated", "Tarih Belirtilmedi"))

            rss_metin = entry.get("summary", "") or entry.get("description", "")
            if len(rss_metin) < 80:
                rss_metin = orijinal_baslik

            if len(sayfa_metni) > len(rss_metin) + 100:
                icerik = sayfa_metni
                print(" → Sayfa içeriği kullanıldı")
            else:
                icerik = rss_metin
                print(" → RSS özeti kullanıldı")

            yeni_baslik, ozet = haberi_islemden_gecir(
                icerik, orijinal_baslik, kategori, yayin_tarihi
            )

            if not ozet or "YETERSIZ" in ozet.upper() or len(ozet.strip()) < 2:
                print(f" → Atlandı (Yetersiz / Yerel): {orijinal_baslik[:60]}")
                continue

            try:
                check_title = supabase.table("haberler").select("id").ilike("baslik", f"%{yeni_baslik[:40]}%").execute()
                if check_title.data:
                    print(f" → Tekrar eden başlık atlandı: {yeni_baslik}")
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
                print(f" ✓ Eklendi → Başlık: {yeni_baslik}")
                print(f" Özet : {ozet}")
            except Exception as e:
                print(f" → Veritabanı ekleme hatası: {e}")

            time.sleep(random.uniform(4, 7))

    print("\n\nTüm işlemler tamamlandı.")


if __name__ == "__main__":
    main()
'''

with open('/mnt/agents/output/main.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("ok", len(code))
