import os
import time
import logging
import asyncio

from dotenv import load_dotenv
from openai import AsyncOpenAI

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# ENVIRONMENT & LOGGING
# =========================================================

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("viyana_ai")


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MODEL = "gpt-4o-mini"
MAX_MESSAGE_LENGTH = 4000
API_TIMEOUT = 30

IS_BOT_ACTIVE = True


# =========================================================
# OPENAI CLIENT
# =========================================================

client = None

if OPENAI_API_KEY:
    client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        timeout=API_TIMEOUT,
        max_retries=0,
    )


# =========================================================
# LANGUAGE DETECTION (Genişletilmiş & Esnek)
# =========================================================

CYRILLIC_CHARS = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
GERMAN_CHARS = set("äöüß")
TURKISH_CHARS = set("çğıöşü")
AZERBAIJANI_CHARS = set("ə")

def detect_language(text):
    text_lower = text.lower()
    letters = [char for char in text_lower if char.isalpha()]

    if not letters:
        return "other"

    # Karakter bazlı kesin kontrol
    if sum(1 for char in letters if char in CYRILLIC_CHARS) >= 1:
        return "ru"
    if sum(1 for char in letters if char in GERMAN_CHARS) > 0:
        return "de"
    if sum(1 for char in letters if char in AZERBAIJANI_CHARS) > 0:
        return "az"
    if sum(1 for char in letters if char in TURKISH_CHARS) > 0:
        return "tr"

    # Genel kelime bazlı sezgisel kontrol (Selam, nasılsın vb. kelimeler için)
    words = set(text_lower.split())
    
    az_keywords = {"men", "sen", "sən", "mən", "necə", "nece", "beli", "heç", "olar", "harda"}
    tr_keywords = {"ben", "sen", "selam", "merhaba", "nasılsın", "ne", "nasıl", "iyi", "evet", "tamam", "görüşürüz"}
    ru_keywords = {"привет", "как", "дела", "что", "да", "нет"}
    de_keywords = {"hallo", "wie", "geht", "gut", "und", "ja", "nein"}

    if words & az_keywords:
        return "az"
    if words & tr_keywords:
        return "tr"
    if words & ru_keywords:
        return "ru"
    if words & de_keywords:
        return "de"

    # Hiçbiri eşleşmezse varsayılan olarak Türkçe/Ortak kabul et ve 4 dile çevir
    return "tr"


def get_targets(source_language):
    if source_language == "az":
        return ["tr", "ru", "de"]
    if source_language == "tr":
        return ["az", "ru", "de"]
    if source_language == "ru":
        return ["az", "tr", "de"]
    if source_language == "de":
        return ["az", "tr", "ru"]
    return ["az", "tr", "ru", "de"]


# =========================================================
# TRANSLATION PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Viyana AI, a professional and strict translation engine.
Translate the source text accurately and naturally into the requested target languages.

CRITICAL RULES:
1. Translate ONLY what is written. Do not add comments, explanations, or extra text.
2. Keep the exact meaning, tone, emojis, and punctuation.
3. Output MUST strictly follow this format for each requested language code (in uppercase):

AZ: [translation]
TR: [translation]
RU: [translation]
DE: [translation]

Do not include any other text outside of this format.
"""


# =========================================================
# TRANSLATION FUNCTION
# =========================================================

async def translate_text(text, source_language, targets):
    if not client:
        return {lang: "⚠️ OpenAI API anahtarı tanımlı değil." for lang in targets}

    target_names = ", ".join(f"{lang.upper()}" for lang in targets)

    user_prompt = (
        f"SOURCE_LANGUAGE: {source_language}\n"
        f"TARGET_LANGUAGES: {target_names}\n\n"
        f"SOURCE_TEXT:\n{text}"
    )

    try:
        logger.info("OpenAI API'ye istek gönderiliyor. Model: %s, Hedefler: %s", MODEL, targets)
        
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=800,
        )

        content = response.choices[0].message.content.strip()
        logger.info("OpenAI'dan gelen ham yanıt:\n%s", content)

        translations = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue

            parts = line.split(":", 1)
            code = parts[0].strip().lower()
            value = parts[1].strip().strip("[]") # Köşeli parantez gelirse temizle

            if code in targets and value:
                translations[code] = value

        # Eksik kalan dil olursa güvenli fallback
        for lang in targets:
            if lang not in translations:
                translations[lang] = "⚠️ Çeviri bu dil için oluşturulamadı."

        return translations

    except Exception as error:
        logger.exception("OpenAI çeviri hatası oluştu: %s", error)
        return {lang: "⚠️ Çeviri sırasında hata oluştu." for lang in targets}


# =========================================================
# COMMANDS
# =========================================================

async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    logger.info("Bot kullanıcı tarafından AKTİF edildi.")
    if update.message:
        await update.message.reply_text("🟢 *Bot aktif edildi.* Çeviri sistemi çalışıyor.", parse_mode="Markdown")

async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = False
    logger.info("Bot kullanıcı tarafından KAPATILDI.")
    if update.message:
        await update.message.reply_text("🔴 *Bot kapatıldı.* Yeni mesajlar çevrilmeyecek.", parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    name = update.effective_user.first_name if update.effective_user else ""
    status_str = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"
    message = (
        f"🤖 *Merhaba {name}!*\n\n"
        f"Ben *Viyana AI* — kesintisiz çeviri botuyum.\n"
        f"Durum: *{status_str}*\n\n"
        f"Komutlar:\n/on — Aç\n/off — Kapat"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not IS_BOT_ACTIVE:
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text or text.startswith("/") or len(text) < 1:
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(f"⚠️ Mesaj çok uzun (Maksimum {MAX_MESSAGE_LENGTH} karakter).")
        return

    if not client:
        await update.message.reply_text("⚠️ OpenAI API anahtarı tanımlı değil.")
        return

    source_language = detect_language(text)
    targets = get_targets(source_language)

    logger.info("Mesaj yakalandı | Metin: '%s' | Kaynak=%s | Hedef=%s", text, source_language, targets)

    translations = await translate_text(
        text=text,
        source_language=source_language,
        targets=targets,
    )

    flags = {
        "az": "🇦🇿",
        "tr": "🇹🇷",
        "ru": "🇷🇺",
        "de": "🇩🇪",
    }

    lines = []
    for lang in targets:
        translation = translations.get(lang, "⚠️ Çeviri alınamadı.")
        lines.append(f"{flags[lang]} {translation}")

    reply = "\n\n".join(lines)
    await update.message.reply_text(reply)


# =========================================================
# ERROR HANDLER & MAIN
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Telegram hatası: %s", context.error, exc_info=context.error)

def main():
    if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
        logger.error("Token veya API anahtarı eksik!")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    application.add_error_handler(error_handler)

    logger.info("======================================")
    logger.info("Viyana AI kusursuz sürüm başlatıldı.")
    logger.info("======================================")

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
