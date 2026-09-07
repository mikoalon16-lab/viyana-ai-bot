import logging
import os
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
from openai import OpenAI

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================================================
# LANGUAGE DETECTION
# =========================================================

def detect_language(text: str) -> str:
    text_lower = text.lower()

    # Rusça (Kiril)
    cyrillic = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    if any(c in cyrillic for c in text_lower):
        return "ru"

    # Almanca
    german_chars = set("äöüß")
    german_words = {
        "und", "der", "die", "das", "ich", "nicht", "ist", "ein", "eine",
        "mit", "auf", "für", "von", "zu", "auch", "wie", "aber", "oder",
        "wenn", "weil", "dass", "schon", "noch", "sehr", "mehr", "kann",
        "haben", "sein", "werden", "machen", "gehen", "kommen"
    }
    if any(c in german_chars for c in text_lower) or any(w in text_lower.split() for w in german_words):
        return "de"

    # İngilizce
    english_words = {
        "the", "and", "is", "are", "was", "were", "have", "has", "had",
        "do", "does", "did", "will", "would", "can", "could", "should",
        "this", "that", "what", "which", "who", "where", "when", "why",
        "how", "not", "yes", "please", "thank", "hello", "hi", "good"
    }
    words = set(text_lower.split())
    if len(words & english_words) >= 2:
        return "en"

    # Varsayılan Türkçe
    return "tr"


# =========================================================
# PROFESYONEL ÇEVİRİ
# =========================================================

async def translate_text(text: str, target_lang: str) -> str:
    if not client:
        return "⚠️ OpenAI API anahtarı tanımlı değil."

    lang_map = {
        "tr": "Turkish",
        "ru": "Russian",
        "de": "German",
        "en": "English"
    }
    target = lang_map.get(target_lang, target_lang)

    system_prompt = (
        f"You are a professional native-level translator. "
        f"Translate the given text into natural, fluent, perfect {target}. "
        f"Rules:\n"
        f"- Translate ONLY the meaning, nothing else.\n"
        f"- Do NOT add explanations, notes, or extra sentences.\n"
        f"- Do NOT invent or change the meaning.\n"
        f"- Keep the original tone and style.\n"
        f"- Return ONLY the pure translation."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=1200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Çeviri hatası ({target_lang}): {e}")
        return f"⚠️ Çeviri hatası ({target_lang})"


# =========================================================
# KOMUTLAR
# =========================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name or ""
    msg = (
        f"🤖 **Merhaba {name}!**\n\n"
        f"Ben **Viyana AI** — profesyonel otomatik çeviri botuyum.\n"
        f"**Ehed** tarafından tasarlandım.\n\n"
        f"🌐 **Nasıl çalışır?**\n"
        f"• Türkçe yaz → Almanca + Rusça\n"
        f"• Rusça yaz → Türkçe + Almanca\n"
        f"• Almanca yaz → Türkçe + Rusça\n"
        f"• İngilizce yaz → Türkçe + Rusça + Almanca\n\n"
        f"Sadece mesaj yaz, gerisini ben hallederim."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "📋 **Viyana AI — Otomatik Çeviri**\n\n"
        "Sadece gruba veya bana mesaj yazman yeterli.\n\n"
        "• **Türkçe** → 🇩🇪 Almanca + 🇷🇺 Rusça\n"
        "• **Rusça** → 🇹🇷 Türkçe + 🇩🇪 Almanca\n"
        "• **Almanca** → 🇹🇷 Türkçe + 🇷🇺 Rusça\n"
        "• **İngilizce** → 🇹🇷 Türkçe + 🇷🇺 Rusça + 🇩🇪 Almanca\n\n"
        "Komutlar:\n"
        "`/start` — Başlat\n"
        "`/help` — Bu yardım\n"
        "`/hakkinda` — Hakkında"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def hakkinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 **Viyana AI**\n\n"
        "Profesyonel otomatik çeviri botu.\n"
        "Türkçe ⇄ Rusça ⇄ Almanca + İngilizce desteği.\n\n"
        "Çeviriler ana dili seviyesinde, doğal ve hatasız yapılır.\n"
        "**Ehed** tarafından tasarlanmıştır."
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# =========================================================
# MESAJ DİNLEYİCİ
# =========================================================

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text.startswith("/") or len(text) < 3:
        return

    if not client:
        await update.message.reply_text("⚠️ OpenAI API anahtarı tanımlı değil.")
        return

    detected = detect_language(text)
    logger.info(f"Dil: {detected} | Mesaj: {text[:60]}...")

    if detected == "tr":
        targets = [("de", "🇩🇪"), ("ru", "🇷🇺")]
    elif detected == "ru":
        targets = [("tr", "🇹🇷"), ("de", "🇩🇪")]
    elif detected == "de":
        targets = [("tr", "🇹🇷"), ("ru", "🇷🇺")]
    else:  # en veya bilinmeyen
        targets = [("tr", "🇹🇷"), ("ru", "🇷🇺"), ("de", "🇩🇪")]

    tasks = [translate_text(text, lang) for lang, _ in targets]
    results = await asyncio.gather(*tasks)

    lines = []
    for (lang, flag), translation in zip(targets, results):
        lines.append(f"{flag} **{translation}**")

    reply = "\n\n".join(lines)
    await update.message.reply_text(reply, parse_mode="Markdown")


# =========================================================
# MAIN
# =========================================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY bulunamadı! Çeviri çalışmayacak.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("hakkinda", hakkinda_command))
    app.add_handler(CommandHandler("about", hakkinda_command))

    app.add_handler(MessageHandler(filters.TEXT & (\~filters.COMMAND), handle_messages))

    logger.info("Viyana AI (Sadece Çeviri) başarıyla başlatıldı!")
    app.run_polling()


if __name__ == "__main__":
    main()
