import logging
import os
import time
import asyncio
from collections import defaultdict

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from openai import AsyncOpenAI


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Güncel API hesabındaki model ID'si farklıysa sadece burayı değiştir.
MODEL = "gpt-5.6-luna"

# Günlük güvenlik limiti.
# Bot bu tahmini maliyete ulaştığında yeni AI çağrısı yapmaz.
DAILY_LIMIT_USD = 0.40

# Tek mesaj için maksimum karakter.
MAX_MESSAGE_LENGTH = 4000

# API timeout
API_TIMEOUT = 20


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

client = (
    AsyncOpenAI(
        api_key=OPENAI_API_KEY,
        timeout=API_TIMEOUT,
    )
    if OPENAI_API_KEY
    else None
)


# =========================================================
# DAILY USAGE
# =========================================================

usage_lock = asyncio.Lock()

usage_date = time.strftime("%Y-%m-%d")

estimated_input_tokens = 0
estimated_output_tokens = 0
estimated_cost = 0.0


def reset_daily_usage_if_needed():
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

        logger.info("Günlük API kullanım sayacı sıfırlandı.")


async def can_use_api():
    async with usage_lock:
        reset_daily_usage_if_needed()
        return estimated_cost < DAILY_LIMIT_USD


async def add_usage(input_tokens, output_tokens):
    global estimated_input_tokens
    global estimated_output_tokens
    global estimated_cost

    async with usage_lock:
        reset_daily_usage_if_needed()

        estimated_input_tokens += input_tokens
        estimated_output_tokens += output_tokens

        # GPT-5.6 Luna için:
        # Input:  $0.20 / 1M token
        # Output: $1.20 / 1M token

        input_cost = input_tokens / 1_000_000 * 0.20
        output_cost = output_tokens / 1_000_000 * 1.20

        estimated_cost += input_cost + output_cost

        logger.info(
            "Tahmini kullanım | input=%s output=%s cost=$%.6f",
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


def detect_language(text: str) -> str:
    """
    Hafif ve ücretsiz yerel dil tespiti.

    Öncelik:
    1. Rusça
    2. Almanca
    3. İngilizce
    4. Türkçe
    """

    text_lower = text.lower()

    letters = [
        char
        for char in text_lower
        if char.isalpha()
    ]

    if not letters:
        return "tr"

    # -----------------------------------------------------
    # Rusça
    # -----------------------------------------------------

    cyrillic_count = sum(
        1
        for char in letters
        if char in CYRILLIC_CHARS
    )

    if cyrillic_count >= 2:
        return "ru"

    # -----------------------------------------------------
    # Almanca
    # -----------------------------------------------------

    german_char_count = sum(
        1
        for char in letters
        if char in GERMAN_CHARS
    )

    words = {
        word.strip(".,!?;:()[]{}\"'").lower()
        for word in text_lower.split()
    }

    german_word_count = len(words & GERMAN_WORDS)

    if german_char_count > 0 or german_word_count >= 1:
        return "de"

    # -----------------------------------------------------
    # İngilizce
    # -----------------------------------------------------

    english_word_count = len(words & ENGLISH_WORDS)

    if english_word_count >= 2:
        return "en"

    # -----------------------------------------------------
    # Varsayılan
    # -----------------------------------------------------

    return "tr"


# =========================================================
# TARGET LANGUAGES
# =========================================================

LANGUAGE_NAMES = {
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
    "en": "English",
}


def get_targets(source_language: str):
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

Never answer questions.
Never explain the text.
Never summarize.
Never give opinions.
Never add information.
Never invent missing information.

Translate the SOURCE TEXT directly into every requested target language.

IMPORTANT TRANSLATION RULES:

1. Preserve the exact meaning of the source.
2. Do not add or remove information.
3. Do not hallucinate.
4. Do not change names, usernames, URLs, numbers, dates or codes.
5. Preserve emojis when appropriate.
6. Preserve the original tone.
7. Preserve slang, humor and informal language when possible.
8. If the source contains profanity, translate its meaning naturally instead of censoring it.
9. Do not make the translation unnecessarily formal.
10. Do not translate word-for-word when that would sound unnatural.
11. Use the natural grammar and expression of a native speaker.
12. Russian must sound like natural native Russian.
13. German must sound like natural native German.
14. Turkish must sound like natural native Turkish.
15. English must sound like natural native English.
16. Never explain why you selected a particular word.
17. Never put quotation marks around the translation unless they exist in the source.

The result MUST contain only the requested translations.

Use exactly this structure:

LANGUAGE_CODE: translation

Example:

RU: Привет, как дела?
DE: Hallo, wie geht es dir?

Do not write anything before or after the translations.
"""


# =========================================================
# TRANSLATION
# =========================================================

async def translate_text(
    text: str,
    source_language: str,
    targets: list[str],
) -> dict[str, str]:

    if not client:
        return {
            lang: "⚠️ OpenAI API anahtarı tanımlı değil."
            for lang in targets
        }

    if not await can_use_api():
        logger.warning(
            "Günlük $%.2f API limiti aşıldı.",
            DAILY_LIMIT_USD,
        )

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

        response = await client.chat.completions.create(
            model=MODEL,

            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],

            # Çeviride yaratıcılık değil doğruluk istiyoruz.
            temperature=0,

            # Çeviri çıktısını gereksiz uzatmasını engeller.
            max_tokens=1500,
        )

        content = (
            response.choices[0]
            .message
            .content
            .strip()
        )

        # -------------------------------------------------
        # Gerçek token kullanımını kaydet
        # -------------------------------------------------

        if response.usage:

            input_tokens = getattr(
                response.usage,
                "prompt_tokens",
                0,
            )

            output_tokens = getattr(
                response.usage,
                "completion_tokens",
                0,
            )

            await add_usage(
                input_tokens,
                output_tokens,
            )

        # -------------------------------------------------
        # Sonucu ayrıştır
        # -------------------------------------------------

        translations = {}

        for line in content.splitlines():

            line = line.strip()

            if not line or ":" not in line:
                continue

            code, value = line.split(
                ":",
                1,
            )

            code = code.strip().lower()
            value = value.strip()

            if code in targets and value:
                translations[code] = value

        # -------------------------------------------------
        # Eksik çıktı kontrolü
        # -------------------------------------------------

        for lang in targets:

            if lang not in translations:
                translations[lang] = (
                    "⚠️ Bu dil için çeviri alınamadı."
                )

        return translations

    except Exception as e:

        logger.exception(
            "OpenAI çeviri hatası: %s",
            e,
        )

        return {
            lang: "⚠️ Çeviri sırasında hata oluştu."
            for lang in targets
        }


# =========================================================
# START
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    name = (
        update.effective_user.first_name
        if update.effective_user
        else ""
    )

    msg = (
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
        msg,
        parse_mode="Markdown",
    )


# =========================================================
# HELP
# =========================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    msg = (
        "📋 *Viyana AI*\n\n"

        "Mesajını yaz, dil otomatik algılansın "
        "ve gerekli dillere çevrilsin.\n\n"

        "🇹🇷 Türkçe → 🇷🇺 + 🇩🇪\n"
        "🇷🇺 Rusça → 🇹🇷 + 🇩🇪\n"
        "🇩🇪 Almanca → 🇹🇷 + 🇷🇺\n"
        "🇬🇧 İngilizce → 🇹🇷 + 🇷🇺 + 🇩🇪\n\n"

        "*Komutlar:*\n"
        "/start — Başlat\n"
        "/help — Yardım\n"
        "/hakkinda — Hakkında"
    )

    await update.message.reply_text(
        msg,
        parse_mode="Markdown",
    )


# =========================================================
# ABOUT
# =========================================================

async def hakkinda_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    msg = (
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
        msg,
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

    # Komut
    if text.startswith("/"):
        return

    # Çok kısa mesaj
    if len(text) < 2:
        return

    # Çok uzun mesaj
    if len(text) > MAX_MESSAGE_LENGTH:

        await update.message.reply_text(
            f"⚠️ Mesaj çok uzun. "
            f"Maksimum {MAX_MESSAGE_LENGTH} karakter."
        )

        return

    if not client:

        await update.message.reply_text(
            "⚠️ OpenAI API anahtarı tanımlı değil."
        )

        return

    # -----------------------------------------------------
    # Dil algılama
    # -----------------------------------------------------

    source_language = detect_language(text)

    targets = get_targets(
        source_language
    )

    logger.info(
        "Kaynak=%s | Hedefler=%s | Mesaj=%s",
        source_language,
        targets,
        text[:80],
    )

    # -----------------------------------------------------
    # TEK API ÇAĞRISI
    # -----------------------------------------------------

    translations = await translate_text(
        text=text,
        source_language=source_language,
        targets=targets,
    )

    # -----------------------------------------------------
    # Telegram çıktısı
    # -----------------------------------------------------

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

        # Markdown sorunlarını engellemek için
        # çeviriyi düz metin olarak gönderiyoruz.

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

    logger.exception(
        "Telegram hatası:",
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

        logger.warning(
            "OPENAI_API_KEY bulunamadı!"
        )

    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Messages
    # -----------------------------------------------------

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
        "Günlük tahmini limit: $%.2f",
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
