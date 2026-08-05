import os
import sys
import json
import html
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

# ponytail: 5-line stdlib .env loader so python automatically reads .env locally.
def load_dotenv(filepath=".env"):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

load_dotenv()

NEWS_URL = os.environ.get("NEWS_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TOPIC_ID = os.environ.get("TELEGRAM_TOPIC_ID") or os.environ.get("MESSAGE_THREAD_ID")
SILENT_IF_EMPTY = os.environ.get("SILENT_IF_EMPTY", "false").lower() == "true"
DISABLE_NOTIFICATION = os.environ.get("DISABLE_NOTIFICATION", "false").lower() == "true"
CACHE_FILE = os.environ.get("CACHE_FILE", "news_cache.json")
CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

# Timezone definition for WIB (Western Indonesia Time / UTC+7)
WIB = timezone(timedelta(hours=7))

INDONESIAN_DAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")

IMPACT_EMOJI = {
    "HIGH": "🔴",
    "MEDIUM": "🟡",
    "LOW": "🔵"
}

def send_telegram(text: str, silent: bool = False) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("[ERROR] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from .env or environment.")
        sys.exit(1)
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload_dict = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "HTML",
        "disable_notification": silent or DISABLE_NOTIFICATION
    }
    
    if TOPIC_ID:
        try:
            payload_dict["message_thread_id"] = int(TOPIC_ID)
        except ValueError:
            print(f"[WARNING] Invalid TELEGRAM_TOPIC_ID '{TOPIC_ID}', ignoring thread ID.")

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[SUCCESS] Telegram message sent. Status: {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Telegram API failed: {e.code} - {e.read().decode('utf-8')}")
        sys.exit(1)

def parse_date(date_val):
    if isinstance(date_val, (int, float)):
        return datetime.fromtimestamp(date_val, timezone.utc)
    clean_date = str(date_val).replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_date)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def fetch_news_data() -> str:
    """
    ponytail: stdlib file cacher (default 1h TTL). Falls back to cached data if ForexFactory returns 429/error.
    """
    now_ts = time.time()
    
    if os.path.exists(CACHE_FILE):
        mtime = os.path.getmtime(CACHE_FILE)
        if now_ts - mtime < CACHE_TTL:
            print(f"[INFO] Using cached news from {CACHE_FILE} ({int(now_ts - mtime)}s old).")
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass

    if not NEWS_URL:
        print("[ERROR] NEWS_URL is not set in .env or environment variables.")
        sys.exit(1)

    print(f"[INFO] Fetching fresh news from {NEWS_URL}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    req = urllib.request.Request(NEWS_URL, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_data = resp.read().decode("utf-8", errors="ignore")
            print(f"[INFO] Successfully fetched {len(raw_data)} bytes.")
            try:
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    f.write(raw_data)
            except Exception as e:
                print(f"[WARNING] Failed to write cache: {e}")
            return raw_data
    except Exception as e:
        print(f"[ERROR] Failed to fetch news from {NEWS_URL}: {e}")
        if os.path.exists(CACHE_FILE):
            print(f"[INFO] Fallback: using cached news from {CACHE_FILE}.")
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        sys.exit(1)

def parse_economic_news(raw_data: str) -> list[str]:
    """
    Parses ForexFactory JSON news feed based solely on High/Medium/Low impact.
    Groups events by impact and WIB time with Indonesian day names.
    Returns list of message chunks formatted for Telegram HTML (each <= 3900 chars).
    """
    try:
        data = json.loads(raw_data)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    now = datetime.now(timezone.utc)
    groups = {}

    CRITICAL_KEYWORDS = ("FOMC", "CPI", "NFP", "FED", "RATE", "INFLATION", "GDP", "PMI", "OIL")

    for item in data:
        impact = str(item.get("impact", "")).upper()
        if impact not in IMPACT_EMOJI:
            continue
        
        date_str = item.get("date") or item.get("time") or item.get("timestamp")
        if not date_str:
            continue
            
        try:
            event_dt = parse_date(date_str)
        except Exception:
            continue

        # ponytail: include full week's upcoming/recent events (from 15 mins ago onwards)
        if (event_dt - now).total_seconds() < -900:
            continue

        title = str(item.get("title", "") or item.get("name", "") or item.get("event", "")).strip()
        country = str(item.get("country", "")).strip().upper()
        if not title:
            continue

        # ponytail: include High & Medium impact, plus Low impact only if title contains critical keywords (e.g. FOMC).
        is_high_med = impact in ("HIGH", "MEDIUM")
        is_low_critical = impact == "LOW" and any(kw in title.upper() for kw in CRITICAL_KEYWORDS)
        if not (is_high_med or is_low_critical):
            continue

        key = (event_dt, impact)
        if key not in groups:
            groups[key] = []
        groups[key].append((country, title))

    if not groups:
        return []

    sorted_keys = sorted(groups.keys(), key=lambda k: k[0])
    blocks = []

    for dt, impact in sorted_keys:
        emoji = IMPACT_EMOJI[impact]
        dt_wib = dt.astimezone(WIB)
        day_name = INDONESIAN_DAYS[dt_wib.weekday()]
        time_str = dt_wib.strftime("%H:%M WIB")
        
        header = f"{emoji} {day_name}, {time_str}"
        lines = [header]
        for country, title in groups[(dt, impact)]:
            safe_title = html.escape(title)
            country_tag = f"<b>[{country}]</b>" if country else ""
            lines.append(f"- {country_tag} - {safe_title}" if country_tag else f"- {safe_title}")
        
        blocks.append("\n".join(lines))

    # ponytail: chunk by whole blocks (max 3900 chars per message) to safely avoid cutting HTML tags in half.
    chunks = []
    current_chunk = []
    current_len = 0

    for block in blocks:
        if current_len + len(block) + 2 > 3900:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
            current_chunk = [block]
            current_len = len(block)
        else:
            current_chunk.append(block)
            current_len += len(block) + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks

def main():
    raw_data = fetch_news_data()
    chunks = parse_economic_news(raw_data)
    
    if chunks:
        print(f"[INFO] Sending {len(chunks)} message chunk(s)...")
        for chunk in chunks:
            send_telegram(chunk, silent=False)
    else:
        print("[INFO] No upcoming economic news found.")
        if not SILENT_IF_EMPTY:
            send_telegram("ℹ️ <b>Economic News Check</b>\n\nNo upcoming economic news found.", silent=True)

if __name__ == "__main__":
    main()

