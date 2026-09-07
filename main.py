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

MODEL = "gpt-5.6-luna"

DAILY_LIMIT_USD = 0.40

MAX_MESSAGE_LENGTH = 4000

API_TIMEOUT = 30


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
# DAILY USAGE
# =========================================================

usage_lock = asyncio.Lock()

usage_date = time.strftime("%Y-%m-%d")

estimated_input_tokens = 0
estimated_output_tokens = 0
estimated_cost = 0.0


def reset_daily_usage():
    global usage_date
    global estimated_input_tokens
    global estimated_output_tokens
    global estimated_cost

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
    global estimated_input_tokens
    global estimated_output_tokens
    global estimated_cost

    async with usage_lock:
        reset_daily_usage()

        estimated_input_tokens += input_tokens
        estimated_output_tokens += output_tokens

        input_cost = (
            input_tokens / 1_000_000
        ) * 0.20

        output_cost = (
            output_tokens / 1_000_000
        ) * 1.20

        estimated_cost += (
            input_cost + output_cost
        )

        logger.info(
            "API kullanım | input=%s | output=%s | maliyet=$%.6f",
            estimated_input_tokens,
            estimated_output_tokens,
            estimated_cost,
        )


# =========================================================
# LANGUAGE DETECTION
# =========================================================

CYRILLIC_CHARS = set(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
)

GERMAN_CHARS = set("äöüß")

TURKISH_CHARS = set("çğıöşü")


GERMAN_WORDS = {
    "und",
    "der",
    "die",
    "das",
    "ich",
    "nicht",
    "ist",
    "ein",
    "eine",
    "mit",
    "auf",
    "für",
    "von",
    "zu",
    "auch",
    "wie",
    "aber",
    "oder",
    "wenn",
    "weil",
    "dass",
    "schon",
    "noch",
    "sehr",
    "mehr",
    "kann",
    "haben",
    "sein",
    "werden",
    "machen",
    "gehen",
    "kommen",
}


ENGLISH_WORDS = {
    "the",
    "and",
    "is",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "can",
    "could",
    "should",
    "this",
    "that",
    "what",
    "which",
    "who",
    "where",
    "when",
    "why",
    "how",
    "not",
    "yes",
    "please",
    "thank",
    "thanks",
    "hello",
    "hi",
    "good",
    "morning",
    "night",
}


TURKISH_WORDS = {
    "ben",
    "sen",
    "biz",
    "siz",
    "bu",
    "şu",
    "bir",
    "ve",
    "ama",
    "için",
    "ile",
    "ne",
    "nasıl",
    "neden",
    "çok",
    "var",
    "yok",
    "değil",
    "gibi",
    "daha",
    "şimdi",
    "bugün",
    "yarın",
    "merhaba",
    "teşekkür",
}


def detect_language(text):
    text_lower = text.lower()

    letters = [
        char
        for char in text_lower
        if char.isalpha()
    ]

    if not letters:
        return "tr"

    words = {
        word.strip(
            ".,!?;:()[]{}\"'“”‘’"
        )
        for word in text_lower.split()
    }

    # Rusça
    cyrillic_count = sum(
        1
        for char in letters
        if char in CYRILLIC_CHARS
    )

    if cyrillic_count >= 2:
        return "ru"

    # Almanca
    german_char_count = sum(
        1
        for char in letters
        if char in GERMAN_CHARS
    )

    german_word_count = len(
        words & GERMAN_WORDS
    )

    if german_char_count > 0:
        return "de"

    if german_word_count >= 1:
        return "de"

    # Türkçe
    turkish_char_count = sum(
        1
        for char in letters
        if char in TURKISH_CHARS
    )

    turkish_word_count = len(
        words & TURKISH_WORDS
    )

    if turkish_char_count > 0:
        return "tr"

    if turkish_word_count >= 1:
        return "tr"

    # İngilizce
    english_word_count = len(
        words & ENGLISH_WORDS
    )

    if english_word_count >= 2:
        return "en"

    # Varsayılan
    return "tr"


# =========================================================
# LANGUAGE CONFIG
# =========================================================

LANGUAGE_NAMES = {
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
    "en": "English",
}


def get_targets(source_language):
    if source_language == "tr":
        return ["ru", "de"]

    if source_language == "ru":
        return ["tr", "de"]

    if source_language == "de":
        return ["tr", "ru"]

    if source_language == "en":
        return ["tr", "ru", "de"]

    return ["tr", "ru", "de"]


# =========================================================
# TRANSLATION PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Viyana AI, a professional translation engine.

Your ONLY job is translation.

Never answer the user's message.
Never have a conversation.
Never explain.
Never summarize.
Never give opinions.
Never add information.
Never invent information.

Translate the source text into every requested target language.

RULES:

1. Preserve the exact meaning.
2. Do not add information.
3. Do not remove information.
4. Never hallucinate.
5. Preserve names.
6. Preserve usernames.
7. Preserve URLs.
8. Preserve numbers.
9. Preserve dates.
10. Preserve codes.
11. Preserve emojis.
12. Preserve the original tone.
13. Preserve slang.
14. Preserve humor.
15. Preserve profanity.
16. Do not censor profanity.
17. Do not make casual text unnecessarily formal.
18. Do not translate word-for-word if it sounds unnatural.
19. Use natural native-level grammar.
20. Russian must sound like natural native Russian.
21. German must sound like natural native German.
22. Turkish must sound like natural native Turkish.
23. English must sound like natural native English.
24. Do not explain translation choices.
25. Do not add quotation marks unless they exist in the source.
26. Output ONLY the translations.

The output MUST use exactly this format:

RU: translation
DE: translation

or:

TR: translation
RU: translation

or:

TR: translation
RU: translation
DE: translation

Use uppercase language codes.

Do not write anything before or after the translations.
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

    if not await can_use_api():
        return {
            lang: "⚠️ Günlük çeviri kullanım limiti doldu."
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
        response = await client.responses.create(
            model=MODEL,
            instructions=SYSTEM_PROMPT,
            input=user_prompt,
            reasoning={
                "effort": "none"
            },
            max_output_tokens=500,
        )

        content = response.output_text.strip()

        if response.usage:
            input_tokens = getattr(
                response.usage,
                "input_tokens",
                0,
            )

            output_tokens = getattr(
                response.usage,
                "output_tokens",
                0,
            )

            await add_usage(
                input_tokens,
                output_tokens,
            )

        translations = {}

        for line in content.splitlines():
            line = line.strip()

            if not line:
                continue

            if ":" not in line:
                continue

            code, value = line.split(
                ":",
                1,
            )

            code = code.strip().lower()
            value = value.strip()

            if code in targets and value:
                translations[code] = value

        for lang in targets:
            if lang not in translations:
                translations[lang] = (
                    "⚠️ Bu dil için çeviri alınamadı."
                )

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
# /START
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

    message = (
        f"🤖 *Merhaba {name}!*\n\n"
        f"Ben *Viyana AI* — otomatik çeviri botuyum.\n"
        f"*Ehed* tarafından tasarlandım.\n\n"
        f"🌐 *Otomatik çeviri:*\n\n"
        f"🇹🇷 Türkçe → 🇷🇺 Rusça + 🇩🇪 Almanca\n"
        f"🇷🇺 Rusça → 🇹🇷 Türkçe + 🇩🇪 Almanca\n"
        f"🇩🇪 Almanca → 🇹🇷 Türkçe + 🇷🇺 Rusça\n"
        f"🇬🇧 İngilizce → 🇹🇷 Türkçe + 🇷🇺 Rusça + 🇩🇪 Almanca\n\n"
        f"Sadece mesajını gönder."
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# =========================================================
# /HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    message = (
        "📋 *Viyana AI*\n\n"
        "Mesajını gönder, dil otomatik algılansın "
        "ve gerekli dillere çevrilsin.\n\n"
        "🇹🇷 Türkçe → 🇷🇺 + 🇩🇪\n"
        "🇷🇺 Rusça → 🇹🇷 + 🇩🇪\n"
        "🇩🇪 Almanca → 🇹🇷 + 🇷🇺\n"
        "🇬🇧 İngilizce → 🇹🇷 + 🇷🇺 + 🇩🇪\n\n"
        "*Komutlar:*\n"
        "/start — Başlat\n"
        "/help — Yardım\n"
        "/hakkinda — Hakkında\n"
        "/about — About"
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# =========================================================
# /HAKKINDA
# =========================================================

async def hakkinda_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    message = (
        "🤖 *Viyana AI*\n\n"
        "Profesyonel otomatik çeviri botu.\n\n"
        "🇹🇷 Türkçe\n"
        "🇷🇺 Rusça\n"
        "🇩🇪 Almanca\n"
        "🇬🇧 İngilizce\n\n"
        "Doğal, anlam odaklı ve "
        "native seviyeye yakın çeviri sistemi.\n\n"
        "*Ehed* tarafından tasarlanmıştır."
    )

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def handle_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    if text.startswith("/"):
        return

    if len(text) < 2:
        return

    if len(text) > MAX_MESSAGE_LENGTH:
        await update.message.reply_text(
            f"⚠️ Mesaj çok uzun.\n"
            f"Maksimum {MAX_MESSAGE_LENGTH} karakter."
        )
        return

    if not client:
        await update.message.reply_text(
            "⚠️ OpenAI API anahtarı tanımlı değil."
        )
        return

    source_language = detect_language(text)

    targets = get_targets(
        source_language
    )

    logger.info(
        "Kaynak=%s | Hedef=%s",
        source_language,
        targets,
    )

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
        translation = translations.get(
            lang,
            "⚠️ Çeviri alınamadı.",
        )

        lines.append(
            f"{flags[lang]} {translation}"
        )

    reply = "\n\n".join(lines)

    await update.message.reply_text(
        reply
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Telegram hatası: %s",
        context.error,
        exc_info=context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN bulunamadı!"
        )
        return

    if not OPENAI_API_KEY:
        logger.error(
            "OPENAI_API_KEY bulunamadı!"
        )
        return

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "hakkinda",
            hakkinda_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "about",
            hakkinda_command,
        )
    )

    # Messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_messages,
        )
    )

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "======================================"
    )

    logger.info(
        "Viyana AI başlatıldı."
    )

    logger.info(
        "Model: %s",
        MODEL,
    )

    logger.info(
        "Günlük uygulama limiti: $%.2f",
        DAILY_LIMIT_USD,
    )

    logger.info(
        "Tek mesaj = tek OpenAI çağrısı."
    )

    logger.info(
        "======================================"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
