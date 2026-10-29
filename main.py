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
# ENVIRONMENT
# =========================================================

load_dotenv()


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI-ın ən ucuz, sürətli və yüksək keyfiyyətli çeviri modeli
MODEL = "gpt-4o-mini"

DAILY_LIMIT_USD = 0.40
MAX_MESSAGE_LENGTH = 4000
API_TIMEOUT = 30


# =========================================================
# BOT STATE (ON / OFF)
# =========================================================

IS_BOT_ACTIVE = True


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("viyana_ai")


# =========================================================
# OPENAI CLIENT
# =========================================================

client = None

if OPENAI_API_KEY:
    client = AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        timeout=API_TIMEOUT,
        max_retries=1,
    )


# =========================================================
# DAILY USAGE & COST TRACKER
# =========================================================

usage_lock = asyncio.Lock()
usage_date = time.strftime("%Y-%m-%d")

estimated_input_tokens = 0
estimated_output_tokens = 0
estimated_cost = 0.0


def reset_daily_usage():
    global usage_date, estimated_input_tokens, estimated_output_tokens, estimated_cost

    today = time.strftime("%Y-%m-%d")

    if today != usage_date:
        usage_date = today
        estimated_input_tokens = 0
        estimated_output_tokens = 0
        estimated_cost = 0.0
        logger.info("Günlük kullanım sayacı sıfırlandı.")


async def can_use_api():
    async with usage_lock:
        reset_daily_usage()
        return estimated_cost < DAILY_LIMIT_USD


async def add_usage(input_tokens, output_tokens):
    global estimated_input_tokens, estimated_output_tokens, estimated_cost

    async with usage_lock:
        reset_daily_usage()

        estimated_input_tokens += input_tokens
        estimated_output_tokens += output_tokens

        # gpt-4o-mini fiyatlandırması ($0.15 / 1M input, $0.60 / 1M output)
        input_cost = (input_tokens / 1_000_000) * 0.15
        output_cost = (output_tokens / 1_000_000) * 0.60

        estimated_cost += (input_cost + output_cost)

        logger.info(
            "API kullanım | input=%s | output=%s | maliyet=$%.6f",
            estimated_input_tokens,
            estimated_output_tokens,
            estimated_cost,
        )


# =========================================================
# LANGUAGE DETECTION
# =========================================================

CYRILLIC_CHARS = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
GERMAN_CHARS = set("äöüß")
TURKISH_CHARS = set("çğıöşü")

GERMAN_WORDS = {
    "und", "der", "die", "das", "ich", "nicht", "ist", "ein", "eine",
    "mit", "auf", "für", "von", "zu", "auch", "wie", "aber", "oder",
    "wenn", "weil", "dass", "schon", "noch", "sehr", "mehr", "kann",
    "haben", "sein", "werden", "machen", "gehen", "kommen",
}

TURKISH_WORDS = {
    "ben", "sen", "biz", "siz", "bu", "şu", "bir", "ve", "ama",
    "için", "ile", "ne", "nasıl", "neden", "çok", "var", "yok",
    "değil", "gibi", "daha", "şimdi", "bugün", "yarın", "merhaba", "teşekkür",
}

ENGLISH_WORDS = {
    "the", "and", "is", "to", "in", "it", "of", "you", "that", "he",
    "was", "for", "on", "are", "with", "as", "his", "they", "at", "be",
    "this", "have", "from", "or", "had", "by", "hot", "but", "some", "what"
}


def detect_language(text):
    text_lower = text.lower()
    letters = [char for char in text_lower if char.isalpha()]

    if not letters:
        return "other"

    words = {
        word.strip(".,!?;:()[]{}\"'“”‘’")
        for word in text_lower.split()
    }

    # Rusça
    cyrillic_count = sum(1 for char in letters if char in CYRILLIC_CHARS)
    if cyrillic_count >= 2:
        return "ru"

    # Almanca
    german_char_count = sum(1 for char in letters if char in GERMAN_CHARS)
    german_word_count = len(words & GERMAN_WORDS)
    if german_char_count > 0 or german_word_count >= 1:
        return "de"

    # Türkçe
    turkish_char_count = sum(1 for char in letters if char in TURKISH_CHARS)
    turkish_word_count = len(words & TURKISH_WORDS)
    if turkish_char_count > 0 or turkish_word_count >= 1:
        return "tr"

    # İngilizce
    english_word_count = len(words & ENGLISH_WORDS)
    if english_word_count >= 1:
        return "en"

    return "other"


# =========================================================
# LANGUAGE CONFIG & TARGETS
# =========================================================

LANGUAGE_NAMES = {
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
    "en": "English",
}


def get_targets(source_language):
    all_langs = ["tr", "ru", "de", "en"]
    if source_language in all_langs:
        return [lang for lang in all_langs if lang != source_language]
    return ["tr", "ru", "de", "en"]


# =========================================================
# TRANSLATION PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Viyana AI, a high-precision professional translation engine.

Your ONLY job is translation.

Never answer the user's message as a chatbot.
Never have a conversation.
Never explain anything.
Never summarize.
Never give opinions or comments.
Never add or invent information.

Translate the source text into every requested target language accurately and naturally.

RULES:
1. Preserve the exact meaning accurately and naturally.
2. Do not add or omit any information.
3. Preserve names, usernames (@name), URLs, numbers, dates, codes, and emojis.
4. Preserve tone, slang, humor, and profanity (do not censor).
5. Output natural native-level grammar for Turkish, Russian, German, and English.
6. Do not write explanations or notes.

The output MUST use exactly this format (only for requested target languages):

TR: translation
RU: translation
DE: translation
EN: translation

Use uppercase language codes. Output ONLY the lines with translations.
"""


# =========================================================
# TRANSLATION FUNCTION
# =========================================================

async def translate_text(text, source_language, targets):
    if not client:
        return {lang: "⚠️ OpenAI API anahtarı tanımlı değil." for lang in targets}

    if not await can_use_api():
        return {lang: "⚠️ Günlük çeviri kullanım limiti doldu." for lang in targets}

    target_names = ", ".join(f"{lang}={LANGUAGE_NAMES[lang]}" for lang in targets)

    user_prompt = (
        f"SOURCE_LANGUAGE: {source_language}\n"
        f"TARGET_LANGUAGES: {target_names}\n\n"
        f"SOURCE_TEXT:\n{text}"
    )

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=600,
        )

        content = response.choices[0].message.content.strip()

        if response.usage:
            await add_usage(
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
            )

        translations = {}

        for line in content.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue

            code, value = line.split(":", 1)
            code = code.strip().lower()
            value = value.strip()

            if code in targets and value:
                translations[code] = value

        for lang in targets:
            if lang not in translations:
                translations[lang] = "⚠️ Bu dil için çeviri alınamadı."

        return translations

    except Exception as error:
        logger.exception("OpenAI çeviri hatası: %s", error)
        return {lang: "⚠️ Çeviri sırasında hata oluştu." for lang in targets}


# =========================================================
# ON / OFF COMMANDS
# =========================================================

async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    logger.info("Bot kullanıcı tarafından AKTİF edildi.")

    if update.message:
        await update.message.reply_text(
            "🟢 *Bot aktif edildi.* Otomatik çeviri sistemi çalışıyor.",
            parse_mode="Markdown",
        )


async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = False
    logger.info("Bot kullanıcı tarafından KAPATILDI.")

    if update.message:
        await update.message.reply_text(
            "🔴 *Bot kapatıldı.* Yeni mesajlar çevrilmeyecek.",
            parse_mode="Markdown",
        )


# =========================================================
# COMMAND HANDLERS
# =========================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    name = update.effective_user.first_name if update.effective_user else ""
    status_str = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"

    message = (
        f"🤖 *Merhaba {name}!*\n\n"
        f"Ben *Viyana AI* — otomatik çeviri (TR, RU, DE, EN) botuyum.\n"
        f"*Ehed* tarafından tasarlandım[span_4](start_span)[span_4](end_span).\n\n"
        f"Durum: *{status_str}*\n\n"
        f"🌐 *Özellikler:*\n"
        f"• Mesajları anında tespit edip otomatik olarak Türkçe, Rusça, Almanca ve İngilizceye çevirir.\n\n"
        f"Komutlar:\n"
        f"/on — Botu açar\n"
        f"/off — Botu kapatır\n"
        f"/help — Yardım"
    )

    await update.message.reply_text(message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    message = (
        "📋 *Viyana AI Yardım*\n\n"
        "Grupta veya özelde yazılan mesajları otomatik olarak algılar ve diğer dillere çevirir (TR, RU, DE, EN)[span_5](start_span)[span_5](end_span).\n\n"
        "*Komutlar:*\n"
        "/start — Başlat\n"
        "/on — Aktif Et\n"
        "/off — Kapat\n"
        "/help — Yardım\n"
        "/hakkinda — Hakkında"
    )

    await update.message.reply_text(message, parse_mode="Markdown")


async def hakkinda_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    message = (
        "🤖 *Viyana AI*\n\n"
        "Otomatik çeviri botu[span_6](start_span)[span_6](end_span).\n\n"
        "1. 🇹🇷 Türkçe\n"
        "2. 🇷🇺 Rusça\n"
        "3. 🇩🇪 Almanca\n"
        "4. 🇬🇧 İngilizce\n\n"
        "*Ehed* tarafından tasarlanmıştır[span_7](start_span)[span_7](end_span)."
    )

    await update.message.reply_text(message, parse_mode="Markdown")


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not IS_BOT_ACTIVE or not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text or text.startswith("/"):
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(
            f"⚠️ Mesaj çok uzun. Maksimum {MAX_MESSAGE_LENGTH} karakter."
        )
        return

    if not client:
        await update.message.reply_text("⚠️ OpenAI API anahtarı tanımlı değil.")
        return

    if len(text) < 2:
        return

    source_language = detect_language(text)
    targets = get_targets(source_language)

    logger.info("Kaynak=%s | Hedef=%s", source_language, targets)

    translations = await translate_text(
        text=text,
        source_language=source_language,
        targets=targets,
    )

    flags = {
        "tr": "🇹🇷",
        "ru": "🇷🇺",
        "de": "🇩🇪",
        "en": "🇬🇧",
    }

    lines = []
    for lang in targets:
        translation = translations.get(lang, "⚠️ Çeviri alınamadı.")
        lines.append(f"{flags[lang]} {translation}")

    reply = "\n\n".join(lines)
    await update.message.reply_text(reply)


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Telegram hatası: %s", context.error, exc_info=context.error)


# =========================================================
# MAIN
# =========================================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY bulunamadı!")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("hakkinda", hakkinda_command))
    application.add_handler(CommandHandler("about", hakkinda_command))

    # Messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_messages,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("======================================")
    logger.info("Viyana AI Translator başlatıldı.")
    logger.info("Model: %s", MODEL)
    logger.info("Günlük limit: $%.2f", DAILY_LIMIT_USD)
    logger.info("======================================")

    application.run_polling(drop_pending_updates=True)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
