"""
ربات تحلیل‌گر بازار رمزارز - نسخه اجرای تکی (برای GitHub Actions)
====================================================================
نسخه ۲: منبع خبر از CryptoPanic (که پلن رایگانش حذف شده) به RSS منابع خبری
معتبر (CoinDesk و Cointelegraph) تغییر کرد - این‌ها رایگان و بدون نیاز به کلید هستن.

مهم: این ربات هیچ معامله‌ای خودش انجام نمی‌ده. فقط تحلیل و اطلاع‌رسانی می‌کنه.
"""

import os
import sys
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

# ==========================================================================
# تنظیمات
# ==========================================================================

COINS_TO_TRACK = ["bitcoin", "ethereum", "tether", "binancecoin"]
PRICE_CHANGE_ALERT_THRESHOLD = 3.0

# منابع خبری معتبر - چون خودشون خبرگزاری شناخته‌شده‌ان، نیازی به فیلتر
# "اعتبار منبع" جدا نیست؛ فقط از همین منابع محدود و شناخته‌شده می‌خونیم
NEWS_RSS_FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
}
MAX_ITEMS_PER_FEED = 8

NEGATIVE_KEYWORDS = [
    "war", "conflict", "sanction", "ban", "hack", "hacked", "crash",
    "collapse", "lawsuit", "sec charges", "bankruptcy", "attack",
    "tension", "military", "seized", "exploit", "rug pull"
]
POSITIVE_KEYWORDS = [
    "approval", "approved", "etf", "adoption", "partnership", "rally",
    "surge", "breakthrough", "upgrade", "listing", "institutional",
    "bullish", "record high"
]

REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CryptoAnalysisBot/1.0)"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ==========================================================================
# اخبار (از RSS منابع معتبر)
# ==========================================================================

def fetch_news(timeout=10):
    """
    اخبار رو از فیدهای RSS منابع معتبر می‌گیره.
    چون هر فید مستقل واکشی می‌شه، اگه یکی خطا بده، بقیه همچنان کار می‌کنن.
    """
    all_items = []
    for source_name, url in NEWS_RSS_FEEDS.items():
        try:
            resp = requests.get(url, timeout=timeout, headers=REQUEST_HEADERS)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:MAX_ITEMS_PER_FEED]
            for item in items:
                title = (item.findtext("title") or "").strip()
                if title:
                    all_items.append({"title": title, "source": source_name})
        except requests.exceptions.RequestException as e:
            logger.error(f"خطا در گرفتن اخبار از {source_name}: {e}")
        except ET.ParseError as e:
            logger.error(f"خطا در پردازش XML اخبار از {source_name}: {e}")
    return all_items


def score_news_sentiment(title):
    title_lower = title.lower()
    matched_negative = [kw for kw in NEGATIVE_KEYWORDS if kw in title_lower]
    matched_positive = [kw for kw in POSITIVE_KEYWORDS if kw in title_lower]
    return len(matched_positive) - len(matched_negative), matched_negative, matched_positive


# ==========================================================================
# قیمت‌ها (CoinGecko)
# ==========================================================================

def fetch_prices(coin_ids, timeout=10):
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(coin_ids), "vs_currencies": "usd", "include_24hr_change": "true"}
    try:
        resp = requests.get(url, params=params, timeout=timeout, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در گرفتن قیمت‌ها: {e}")
        return {}
    except ValueError as e:
        logger.error(f"خطا در پردازش پاسخ JSON قیمت‌ها: {e}")
        return {}


# ==========================================================================
# ساخت پیام
# ==========================================================================

def build_analysis_message(news_items, prices):
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 گزارش تحلیل بازار رمزارز — {now_str}", "", "💰 قیمت‌ها:"]

    if not prices:
        lines.append("  (دریافت قیمت‌ها ناموفق بود)")
    else:
        for coin_id, data in prices.items():
            usd = data.get("usd")
            change = data.get("usd_24h_change")
            if usd is None or change is None:
                continue
            arrow = "🟢" if change >= 0 else "🔴"
            alert_flag = " ⚠️ تغییر قابل توجه" if abs(change) >= PRICE_CHANGE_ALERT_THRESHOLD else ""
            lines.append(f"  {arrow} {coin_id}: ${usd:,.2f} ({change:+.2f}% در ۲۴ساعت){alert_flag}")

    lines.append("")
    lines.append("📰 اخبار مهم (از منابع معتبر):")

    total_sentiment = 0
    shown = 0
    for item in news_items:
        title = item.get("title", "")
        source = item.get("source", "")
        sentiment, neg, pos = score_news_sentiment(title)
        total_sentiment += sentiment
        if shown < 6:
            tag = "🔴" if sentiment < 0 else ("🟢" if sentiment > 0 else "⚪")
            lines.append(f"  {tag} [{source}] {title}")
            shown += 1

    if shown == 0:
        lines.append("  (خبری در این بازه دریافت نشد)")

    lines.append("")
    if total_sentiment > 1:
        lines.append("🟢 فضای خبری کلی: نسبتاً مثبت")
    elif total_sentiment < -1:
        lines.append("🔴 فضای خبری کلی: نسبتاً منفی / پرتنش")
    else:
        lines.append("⚪ فضای خبری کلی: خنثی / نامشخص")

    lines.append("")
    lines.append("⚠️ این پیام صرفاً تحلیل خودکار و اطلاع‌رسانیه، توصیه مالی نیست.")
    lines.append("تصمیم خرید/فروش همیشه با خودته.")
    return "\n".join(lines)


# ==========================================================================
# ارسال به تلگرام
# ==========================================================================

def send_telegram_message(text, bot_token, chat_id, timeout=10):
    if not bot_token or not chat_id:
        logger.error("توکن یا چت‌آیدی تلگرام تنظیم نشده (باید در GitHub Secrets ست بشه).")
        logger.info("\n" + text)
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, data=payload, timeout=timeout)
        if resp.status_code == 400:
            # این خطا معمولاً یعنی chat_id اشتباهه یا کاربر هنوز به ربات
            # پیام /start نزده - این پیام رو واضح‌تر تو لاگ می‌ذاریم
            logger.error(
                "خطای 400 از تلگرام - معمولاً یعنی: (۱) chat_id اشتباهه، یا "
                "(۲) هنوز به ربات خودت تو تلگرام پیام /start نزدی. "
                f"پاسخ کامل تلگرام: {resp.text}"
            )
            return False
        resp.raise_for_status()
        logger.info("پیام با موفقیت به تلگرام ارسال شد.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در ارسال پیام تلگرام: {e}")
        return False


# ==========================================================================
# اجرای یک چرخه
# ==========================================================================

def run_analysis_cycle(bot_token, chat_id):
    logger.info("شروع چرخه تحلیل...")
    news_items = fetch_news()
    prices = fetch_prices(COINS_TO_TRACK)
    message = build_analysis_message(news_items, prices)
    sent = send_telegram_message(message, bot_token, chat_id)
    logger.info("چرخه تحلیل تمام شد.")
    return message, sent


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    sent = False
    try:
        message, sent = run_analysis_cycle(bot_token, chat_id)
    except Exception as e:
        logger.error(f"خطای پیش‌بینی‌نشده: {e}", exc_info=True)
        sys.exit(1)
        return

    if not sent:
        sys.exit(1)


if __name__ == "__main__":
    main()
