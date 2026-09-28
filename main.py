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

# Maliyet dostu ve en yüksek çeviri doğruluğuna sahip model
MODEL = "gpt-4o-mini"

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
        max_retries=0,
    )


# =========================================================
# USAGE TRACKING (Limitsiz)
# =========================================================

usage_lock = asyncio.Lock()
estimated_input_tokens = 0
estimated_output_tokens = 0
estimated_cost = 0.0


async def add_usage(input_tokens, output_tokens):
    global estimated_input_tokens
    global estimated_output_tokens
    global estimated_cost

    async with usage_lock:
        estimated_input_tokens += input_tokens
        estimated_output_tokens += output_tokens

        input_cost = (input_tokens / 1_000_000) * 0.15
        output_cost = (output_tokens / 1_000_000) * 0.60
        estimated_cost += input_cost + output_cost

        logger.info(
            "API kullanım | input=%s | output=%s | toplam maliyet=$%.6f",
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
AZERBAIJANI_CHARS = set("ə")

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

AZERBAIJANI_WORDS = {
    "mən", "sən", "biz", "siz", "bəli", "xeyr", "necə", "harada",
    "haqqında", "üçün", "yoxdur", "təşəkkür", "sağol", "sağ", "ol",
    "yaxşı", "bağışlayın", "çox", "nə", "kim", "bu", "o", "haradan"
}


def detect_language(text):
    text_lower = text.lower()
    letters = [char for char in text_lower if char.isalpha()]

    if not letters:
        return "other"

    words = {word.strip(".,!?;:()[]{}\"'“”‘’") for word in text_lower.split()}

    if sum(1 for char in letters if char in CYRILLIC_CHARS) >= 2:
        return "ru"

    if sum(1 for char in letters if char in GERMAN_CHARS) > 0 or len(words & GERMAN_WORDS) >= 1:
        return "de"

    if sum(1 for char in letters if char in AZERBAIJANI_CHARS) > 0 or len(words & AZERBAIJANI_WORDS) >= 1:
        return "az"

    if sum(1 for char in letters if char in TURKISH_CHARS) > 0 or len(words & TURKISH_WORDS) >= 1:
        return "tr"

    return "other"


# =========================================================
# LANGUAGE CONFIG & TARGETS
# =========================================================

LANGUAGE_NAMES = {
    "az": "Azerbaijani",
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
}


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
# TRANSLATION PROMPT (Sıkı Kurallı & Net Çeviri)
# =========================================================

SYSTEM_PROMPT = """
You are Viyana AI, a strict and professional human-level translation engine.
Your absolute duty is to translate the given text accurately, naturally, and precisely.

STRICT RULES:
1. Translate ONLY what is written. Do not add any extra words, comments, notes, explanations, or interpretations.
2. Never hallucinate or invent information.
3. Keep the exact meaning, tone, slang, profanity, emojis, numbers, URLs, and punctuation context of the original text.
4. Do not answer questions or converse if the text is a question or conversation; just translate the text itself.
5. Provide natural, fluent, native-level phrasing.
6. Output MUST strictly follow this format and nothing else:

AZ: [translation]
TR: [translation]
RU: [translation]
DE: [translation]

Do not write anything else before or after this format.
"""


# =========================================================
# TRANSLATION FUNCTION
# =========================================================

async def translate_text(
    text,
    source_language,
    targets,
):
    if not client:
        return {
            lang: "⚠️ OpenAI API anahtarı tanımlı değil."
            for lang in targets
        }

    target_names = ", ".join(
        f"{lang}={LANGUAGE_NAMES[lang]}"
        for lang in targets
    )

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
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # Yaratıcılığı sıfıra yakın tutarak tam ve sadık çeviri sağlar
            max_tokens=800,
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
        logger.exception(
            "OpenAI çeviri hatası: %s",
            error,
        )

        return {
            lang: "⚠️ Çeviri sırasında hata oluştu."
            for lang in targets
        }


# =========================================================
# ON / OFF COMMANDS
# =========================================================

async def on_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    logger.info("Bot kullanıcı tarafından AKTİF edildi.")

    if update.message:
        await update.message.reply_text(
            "🟢 *Bot aktif edildi.* Çeviri sistemi çalışıyor.",
            parse_mode="Markdown",
        )


async def off_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = False
    logger.info("Bot kullanıcı tarafından KAPATILDI.")

    if update.message:
        await update.message.reply_text(
            "🔴 *Bot kapatıldı.* Yeni mesajlar çevrilmeyecek.",
            parse_mode="Markdown",
        )


# =========================================================
# /START & OTHER COMMANDS
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    name = ""
    if update.effective_user:
        name = update.effective_user.first_name or ""

    status_str = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"

    message = (
        f"🤖 *Merhaba {name}!*\n\n"
        f"Ben *Viyana AI* — limitsiz, saf ve kusursuz çeviri botuyum.\n"
        f"Durum: *{status_str}*\n\n"
        f"🌐 *Desteklenen Diller:*\n"
        f"🇦🇿 Azərbaycan | 🇹🇷 Türkçe | 🇷🇺 Русский | 🇩🇪 Deutsch\n\n"
        f"Komutlar:\n"
        f"/on — Botu açar\n"
        f"/off — Botu kapatır"
    )

    await update.message.reply_text(message, parse_mode="Markdown")


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    message = (
        "📋 *Viyana AI Yardım*\n\n"
        "Mesajını gönder, kelimesi kelimesine değil, "
        "tam anlamıyla ve insan gibi diğer dillere aktarılsın.\n\n"
        "/on — Aktif et\n"
        "/off — Kapat"
    )
    await update.message.reply_text(message, parse_mode="Markdown")


async def hakkinda_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    message = "🤖 *Viyana AI*\nEkstra yorum yapmayan, sadece tam çeviri yapan sistem."
    await update.message.reply_text(message, parse_Mode="Markdown")


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not IS_BOT_ACTIVE:
        return
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text or text.startswith("/") or len(text) < 2:
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(f"⚠️ Mesaj çok uzun (Maksimum {MAX_MESSAGE_LENGTH} karakter).")
        return

    if not client:
        await update.message.reply_text("⚠️ OpenAI API anahtarı tanımlı değil.")
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
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Telegram hatası: %s", context.error, exc_info=context.error)


# =========================================================
# MAIN
# =========================================================

def main():
    if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
        logger.error("Token veya API anahtarı eksik!")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("hakkinda", hakkinda_command))
    application.add_handler(CommandHandler("about", hakkinda_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    application.add_error_handler(error_handler)

    logger.info("======================================")
    logger.info("Viyana AI başlatıldı (Saf Çeviri Modu - Model: %s)", MODEL)
    logger.info("======================================")

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
