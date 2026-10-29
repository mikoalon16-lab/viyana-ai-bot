import os
import logging
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_MESSAGE_LENGTH = 4000
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
# FAILOVER PROVIDERS (YEDEK SİSTEM)
# =========================================================

PROVIDERS = [
    {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    {
        "name": "Cerebras",
        "env_key": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama3.1-8b",
    },
    {
        "name": "Gemini",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
    },
    {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-4o-mini",
    },
    {
        "name": "Mistral",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
    {
        "name": "NVIDIA",
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-8b-instruct",
    },
]

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
}

TURKISH_WORDS = {
    "ben", "sen", "biz", "siz", "bu", "şu", "bir", "ve", "ama",
    "için", "ile", "ne", "nasıl", "neden", "çok", "var", "yok",
    "değil", "gibi", "daha", "şimdi", "bugün", "yarın", "merhaba",
}

ENGLISH_WORDS = {
    "the", "and", "is", "to", "in", "it", "of", "you", "that", "he",
    "was", "for", "on", "are", "with", "as", "his", "they", "at", "be",
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

    if sum(1 for char in letters if char in TURKISH_CHARS) > 0 or len(words & TURKISH_WORDS) >= 1:
        return "tr"

    if len(words & ENGLISH_WORDS) >= 1:
        return "en"

    return "other"

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
    return all_langs

# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Viyana AI, a high-precision professional translation engine.

Your ONLY job is translation.

Never answer the user's message as a chatbot.
Never have a conversation.
Never explain anything.
Never summarize.
Never give opinions, comments, or extra conversational phrases.
Never add or invent information.

Translate the source text into every requested target language with perfect natural native fluency.

RULES:
1. Preserve the exact meaning accurately, naturally, and idiomatically.
2. Do not add, omit, or alter any information.
3. Preserve names, usernames (@name), URLs, numbers, dates, codes, and emojis.
4. Preserve tone, slang, humor, and profanity (do not censor).
5. Output natural native-level grammar for Turkish, Russian, German, and English.
6. Do not write explanations, greetings, or notes.

The output MUST use exactly this format (only for requested target languages):

TR: translation
RU: translation
DE: translation
EN: translation

Use uppercase language codes. Output ONLY the lines with translations.
"""

# =========================================================
# MULTI-PROVIDER TRANSLATION EXECUTION
# =========================================================

async def request_translation_from_provider(provider, user_prompt):
    api_key = os.getenv(provider["env_key"])
    if not api_key:
        return None

    kwargs = {
        "api_key": api_key,
        "timeout": 15,
        "max_retries": 0,
    }
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]

    async with AsyncOpenAI(**kwargs) as client:
        response = await client.chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1000,
        )
        return response.choices[0].message.content.strip()

async def translate_text(text, source_language, targets):
    target_names = ", ".join(f"{lang}={LANGUAGE_NAMES[lang]}" for lang in targets)
    user_prompt = (
        f"SOURCE_LANGUAGE: {source_language}\n"
        f"TARGET_LANGUAGES: {target_names}\n\n"
        f"SOURCE_TEXT:\n{text}"
    )

    content = None
    successful_provider = None

    # Tüm API sağlayıcılarını sırayla dener
    for provider in PROVIDERS:
        try:
            logger.info("Çeviri deneniyor provider=%s", provider["name"])
            res = await request_translation_from_provider(provider, user_prompt)
            if res and len(res) > 5:
                content = res
                successful_provider = provider["name"]
                logger.info("Çeviri başarıyla tamamlandı via %s", successful_provider)
                break
        except Exception as error:
            logger.warning("Provider %s başarısız oldu, sonraki servise geçiliyor. Hata: %s", provider["name"], error)

    if not content:
        return {lang: "⚠️ Tüm çeviri servisleri geçici olarak yanıt vermiyor." for lang in targets}

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
            translations[lang] = "⚠️ Çeviri alınamadı."

    return translations

# =========================================================
# BOT COMMANDS & HANDLERS
# =========================================================

async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    if update.message:
        await update.message.reply_text("🟢 *Bot aktif edildi.* Otomatik çeviri çalışıyor.", parse_mode="Markdown")

async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = False
    if update.message:
        await update.message.reply_text("🔴 *Bot kapatıldı.*", parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    name = update.effective_user.first_name if update.effective_user else ""
    status_str = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"
    message = (
        f"🤖 *Merhaba {name}!*\n\n"
        f"Ben *Viyana AI* — otomatik çoklu dil çeviri botuyum.\n"
        f"*Ehed* tarafından tasarlandım.\n\n"
        f"Durum: *{status_str}*\n\n"
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
        "Mesajları otomatik algılar ve diğer dillere (TR, RU, DE, EN) doğal şekilde çevirir.\n\n"
        "*Komutlar:*\n"
        "/start — Başlat\n"
        "/on — Aktif Et\n"
        "/off — Kapat\n"
        "/help — Yardım"
    )
    await update.message.reply_text(message, parse_mode="Markdown")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not IS_BOT_ACTIVE or not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    if not text or text.startswith("/") or len(text) < 2:
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(f"⚠️ Mesaj çok uzun. Maksimum {MAX_MESSAGE_LENGTH} karakter.")
        return

    source_language = detect_language(text)
    targets = get_targets(source_language)

    translations = await translate_text(text=text, source_language=source_language, targets=targets)

    flags = {"tr": "🇹🇷", "ru": "🇷🇺", "de": "🇩🇪", "en": "🇬🇧"}
    lines = []
    for lang in targets:
        translation = translations.get(lang, "⚠️ Çeviri alınamadı.")
        lines.append(f"{flags[lang]} {translation}")

    reply = "\n\n".join(lines)
    await update.message.reply_text(reply)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Telegram hatası: %s", context.error, exc_info=context.error)

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN bulunamadı!")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    application.add_error_handler(error_handler)

    logger.info("Viyana AI (Otomatik Yedeklemeli Çeviri Sistemi) başlatıldı.")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
