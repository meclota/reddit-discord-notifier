import feedparser
import requests
import time
import os

# Environment variables
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
RSS_URLS_STR = os.getenv("RSS_URLS", "")  # Virgülle ayrılmış liste, ör: url1,url2
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 300))  # saniye, varsayılan 5 dk

if not WEBHOOK_URL:
    print("HATA: DISCORD_WEBHOOK_URL environment variable eksik!")
    exit(1)

if not RSS_URLS_STR:
    print("HATA: RSS_URLS environment variable eksik! En az bir subreddit RSS ekle.")
    exit(1)

# URL'leri listeye çevir (virgülle ayrılmış, boşlukları temizle)
rss_urls = [url.strip() for url in RSS_URLS_STR.split(",") if url.strip()]

print(f"Reddit RSS Notifier başladı... Takip edilen subreddit sayısı: {len(rss_urls)}")

# Her subreddit için ayrı seen set (tekrar göndermemek için)
seen_per_feed = {url: set() for url in rss_urls}

def send_to_discord(title, link, summary="", subreddit=""):
    payload = {
        "embeds": [{
            "title": title,
            "url": link,
            "description": summary[:800] + "..." if len(summary) > 800 else summary,
            "color": 16729344,  # Turuncu-kırmızı
            "footer": {"text": f"r/{subreddit}" if subreddit else ""}
        }]
    }
    try:
        response = requests.post(WEBHOOK_URL, json=payload)
        if response.status_code in (200, 204):
            print(f"Gönderildi: {title} ({subreddit})")
        else:
            print(f"Gönderim hatası ({response.status_code}): {response.text}")
    except Exception as e:
        print(f"Gönderim hatası: {e}")

while True:
    for rss_url in rss_urls:
        try:
            feed = feedparser.parse(rss_url)
            if 'entries' not in feed or not feed.entries:
                print(f"Feed boş veya hata: {rss_url}")
                continue

            # Subreddit adını çıkar (güzel footer için)
            subreddit_name = rss_url.split("/r/")[1].split("/")[0] if "/r/" in rss_url else "Bilinmeyen"

            for entry in reversed(feed.entries):  # En yeni baştan
                entry_id = entry.get('id') or entry.get('link') or entry.title
                if entry_id not in seen_per_feed[rss_url]:
                    summary = entry.get('summary') or entry.get('content', [{}])[0].get('value', '') or ''
                    send_to_discord(entry.title, entry.link, summary, subreddit_name)
                    seen_per_feed[rss_url].add(entry_id)
                    time.sleep(1)  # Rate limit için kısa ara
        except Exception as e:
            print(f"Feed işleme hatası ({rss_url}): {e}")

    time.sleep(CHECK_INTERVAL)
