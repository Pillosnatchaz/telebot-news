import os
import sys
import json
import re
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

# Timezone definition for WIB (Western Indonesia Time / UTC+7)
WIB = timezone(timedelta(hours=7))

# Keywords for high-impact market moving economic events
CRITICAL_KEYWORDS = ["CPI", "FOMC", "NFP", "NON-FARM PAYROLLS", "FED RATE", "INTEREST RATE", "INFLATION", "PPI", "GDP"]

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
            print(f"[SUCCESS] Telegram message sent (topic={TOPIC_ID}, silent={silent or DISABLE_NOTIFICATION}). Status: {resp.status}")
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Telegram API failed: {e.code} - {e.read().decode('utf-8')}")
        sys.exit(1)

def format_event_time(date_str: str):
    """
    Parses date timestamp and formats precise countdown: 'in X hours Y minutes (HH:MM WIB)'.
    Returns tuple: (minutes_total: int, time_label: str)
    """
    try:
        now = datetime.now(timezone.utc)
        if isinstance(date_str, (int, float)):
            event_time = datetime.fromtimestamp(date_str, timezone.utc)
        else:
            clean_date = str(date_str).replace("Z", "+00:00")
            event_time = datetime.fromisoformat(clean_date)
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
        
        diff = event_time - now
        minutes_total = int(diff.total_seconds() // 60)
        time_wib = event_time.astimezone(WIB).strftime("%H:%M WIB")
        
        if minutes_total > 0:
            hours = minutes_total // 60
            mins = minutes_total % 60
            if hours > 0:
                label = f"in {hours} hour{'s' if hours > 1 else ''} {mins} minute{'s' if mins != 1 else ''} ({time_wib})"
            else:
                label = f"in {mins} minute{'s' if mins != 1 else ''} ({time_wib})"
        elif minutes_total > -60:
            label = f"releasing right now / recent ({time_wib})"
        else:
            label = f"passed ({abs(minutes_total)//60}h ago)"
            
        return minutes_total, label
    except Exception:
        return 99999, f"at {date_str}"

def parse_economic_news(raw_data: str):
    """
    Parses JSON calendar feed or HTML text for upcoming CPI/FOMC/NFP events.
    Returns list of upcoming events sorted by closest time first.
    """
    upcoming_events = []
    
    # 1. Parse JSON feed (ForexFactory / Economic Calendar API)
    try:
        data = json.loads(raw_data)
        if isinstance(data, list):
            for item in data:
                title = str(item.get("title", "") or item.get("name", "") or item.get("event", "")).strip()
                country = str(item.get("country", "")).strip()
                title_upper = title.upper()
                impact = str(item.get("impact", "")).upper()
                date_str = item.get("date") or item.get("time") or item.get("timestamp")
                
                is_critical = any(kw in title_upper for kw in CRITICAL_KEYWORDS) or impact in ["HIGH", "CRITICAL"]
                
                if is_critical and title and date_str:
                    mins_left, time_label = format_event_time(date_str)
                    
                    # Only include upcoming events (future or releasing in next 24h)
                    if mins_left >= -15:
                        full_name = f"[{country}] {title}" if country else title
                        upcoming_events.append((mins_left, full_name, time_label))
            
            # Sort upcoming events (closest time first)
            upcoming_events.sort(key=lambda x: x[0])
            
            if upcoming_events:
                return [(e[1], e[2]) for e in upcoming_events]
    except Exception:
        pass

    # 2. ponytail: Fallback regex parser for plain text / HTML content
    lines = raw_data.splitlines()
    for line in lines:
        line_upper = line.upper()
        for kw in CRITICAL_KEYWORDS:
            if kw in line_upper:
                clean_text = re.sub(r'<[^>]+>', ' ', line).strip()
                if 5 < len(clean_text) < 120:
                    time_match = re.search(r'\b(\d{1,2}:\d{2}\s*(?:AM|PM|UTC)?)\b', clean_text, re.IGNORECASE)
                    time_str = f"at {time_match.group(1)} WIB" if time_match else "scheduled today"
                    upcoming_events.append((0, clean_text, time_str))
                break

    return [(e[1], e[2]) for e in upcoming_events]

def main():
    if not NEWS_URL:
        print("[ERROR] NEWS_URL is not set in .env or environment variables.")
        sys.exit(1)

    print(f"[INFO] Fetching news from {NEWS_URL}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }
    req = urllib.request.Request(NEWS_URL, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_data = resp.read().decode("utf-8", errors="ignore")
            print(f"[INFO] Successfully fetched {len(raw_data)} bytes.")
    except Exception as e:
        print(f"[ERROR] Failed to fetch news from {NEWS_URL}: {e}")
        sys.exit(1)

    events = parse_economic_news(raw_data)
    
    if events:
        print(f"[INFO] Found {len(events)} upcoming critical events!")
        alerts = ["🚨 <b>CRITICAL ECONOMIC NEWS ALERT</b>"]
        for title, time_info in events[:5]:
            alerts.append(f"⚠️ There will be <b>{title}</b> {time_info}!")
        
        # Send critical news alerts with audible notification sound
        send_telegram("\n\n".join(alerts), silent=False)
    else:
        print("[INFO] No upcoming critical economic news (CPI/FOMC/NFP) scheduled right now.")
        if not SILENT_IF_EMPTY:
            # Send status checks silently without notification sound/vibration
            send_telegram("ℹ️ <b>Hourly Economic News Check</b>\n\nNo upcoming critical events (CPI/FOMC/NFP) scheduled right now.", silent=True)

if __name__ == "__main__":
    main()
