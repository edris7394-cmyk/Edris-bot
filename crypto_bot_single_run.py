"""
ربات تحلیل‌گر بازار رمزارز - نسخه اجرای تکی (برای GitHub Actions)
====================================================================
این نسخه یه بار اجرا می‌شه و تموم می‌شه (بر خلاف نسخه اصلی که حلقه بی‌نهایته).
دلیلش اینه که GitHub Actions هر بار از نو workflow رو اجرا می‌کنه، پس نیازی
به حلقه و sleep نیست - خود GitHub هر ۱۵ دقیقه یه بار این اسکریپت رو صدا می‌زنه.

توکن و چت‌آیدی تلگرام از environment variables خونده می‌شن (نه از داخل کد)،
چون این فایل قراره روی گیت‌هاب آپلود بشه و نباید هیچ اطلاعات حساسی توش باشه.
این مقادیر باید به‌عنوان "Repository Secret" در تنظیمات گیت‌هاب ست بشن.

مهم: این ربات هیچ معامله‌ای خودش انجام نمی‌ده. فقط تحلیل و اطلاع‌رسانی می‌کنه.
"""

import os
import sys
import logging
from datetime import datetime, timezone

import requests

# ==========================================================================
# تنظیمات (این‌ها رو می‌تونی تغییر بدی، اما توکن/چت‌آیدی از GitHub Secrets میان)
# ==========================================================================

COINS_TO_TRACK = ["bitcoin", "ethereum", "tether", "binancecoin"]
PRICE_CHANGE_ALERT_THRESHOLD = 3.0

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def fetch_news(timeout=10):
    url = "https://cryptopanic.com/api/v1/posts/"
    params = {"public": "true", "kind": "news", "filter": "hot"}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در گرفتن اخبار: {e}")
        return []
    except ValueError as e:
        logger.error(f"خطا در پردازش پاسخ JSON اخبار: {e}")
        return []


def is_low_quality_news(news_item):
    votes = news_item.get("votes", {}) or {}
    negative_signal = votes.get("toxic", 0) + votes.get("negative", 0)
    positive_signal = votes.get("positive", 0) + votes.get("important", 0) + votes.get("liked", 0)
    if negative_signal > 2 and negative_signal > positive_signal:
        return True
    if not news_item.get("source", {}).get("title"):
        return True
    return False


def score_news_sentiment(title):
    title_lower = title.lower()
    matched_negative = [kw for kw in NEGATIVE_KEYWORDS if kw in title_lower]
    matched_positive = [kw for kw in POSITIVE_KEYWORDS if kw in title_lower]
    return len(matched_positive) - len(matched_negative), matched_negative, matched_positive


def fetch_prices(coin_ids, timeout=10):
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(coin_ids), "vs_currencies": "usd", "include_24hr_change": "true"}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در گرفتن قیمت‌ها: {e}")
        return {}
    except ValueError as e:
        logger.error(f"خطا در پردازش پاسخ JSON قیمت‌ها: {e}")
        return {}


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
    lines.append("📰 اخبار مهم (پس از فیلتر اخبار کم‌اعتبار):")

    filtered_count = 0
    total_sentiment = 0
    shown = 0
    for item in news_items:
        if is_low_quality_news(item):
            filtered_count += 1
            continue
        title = item.get("title", "")
        sentiment, neg, pos = score_news_sentiment(title)
        total_sentiment += sentiment
        if shown < 5:
            tag = "🔴" if sentiment < 0 else ("🟢" if sentiment > 0 else "⚪")
            lines.append(f"  {tag} {title}")
            shown += 1

    if shown == 0:
        lines.append("  (خبر قابل اعتمادی در این بازه پیدا نشد)")

    lines.append(f"\n  (تعداد {filtered_count} خبر به‌دلیل کیفیت پایین یا منبع نامعتبر فیلتر شد)")

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


def send_telegram_message(text, bot_token, chat_id, timeout=10):
    if not bot_token or not chat_id:
        logger.error("توکن یا چت‌آیدی تلگرام تنظیم نشده (باید در GitHub Secrets ست بشه).")
        logger.info("\n" + text)
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, data=payload, timeout=timeout)
        resp.raise_for_status()
        logger.info("پیام با موفقیت به تلگرام ارسال شد.")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در ارسال پیام تلگرام: {e}")
        return False


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

    sent = False  # مقداردهی اولیه، تا در صورت بروز خطای زودهنگام هم متغیر تعریف‌شده باشه
    try:
        message, sent = run_analysis_cycle(bot_token, chat_id)
    except Exception as e:
        logger.error(f"خطای پیش‌بینی‌نشده: {e}", exc_info=True)
        sys.exit(1)
        return  # لایه ایمنی اضافه، برای وقتی که sys.exit به هر دلیلی جلوگیری نکنه از ادامه اجرا

    if not sent:
        # اگه ارسال ناموفق بود (مثلاً توکن اشتباه)، exit code غیرصفر بده
        # تا تو تب Actions گیت‌هاب به‌صورت "failed" علامت بخوره و متوجه بشی
        sys.exit(1)


if __name__ == "__main__":
    main()
