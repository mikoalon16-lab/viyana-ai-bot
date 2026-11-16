import os
import json
import logging
from collections import defaultdict, deque

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

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_MESSAGE_LENGTH = 4000
CONTEXT_SIZE = 6
IS_BOT_ACTIVE = True

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("viyana_ai")

# Yalnizca guclu/orta seviye modeller. 8B yedek modeller kaldirildi.
# Bir saglayici teknik hata verirse siradakine gecilir.
PROVIDERS = [
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
        "model": "gpt-4.1-mini",
    },
    {
        "name": "Mistral",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
    {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
]

# Cevrilmemesi gereken kisi/ittifak/oyuncu adlarini buraya ekleyebilirsin.
# Adlar varsayilan olarak yazildiklari bicimde korunur.
KNOWN_NAMES = [
    "Ehed",
    "Fırat",
    "Viyana",
    "Unprincipled",
]

GLOSSARY = """
Oyun baglami icin terim tercihleri:
- трон / throne = taht (taç degil)
- межсерверная битва / межсерверная война = sunucular arasi savas
- альянс = ittifak
- регион / территория = bolge
- лидер = lider
- алмазы = elmaslar
- очередь за троном = taht sirasi / tahta cikma sirasi (cumle baglamina gore)
Terimleri yalnizca baglam gercekten uyuyorsa kullan. Kaynakta olmayan oyun bilgisi ekleme.
"""

SYSTEM_PROMPT = f"""
You are Viyana AI, a careful Turkish-Russian chat translator for a gaming community.

SUPPORTED LANGUAGES:
- Turkish (tr)
- Russian (ru)

TASK:
Translate ONLY the current SOURCE_TEXT directly from Turkish to Russian or from
Russian to Turkish. Do not use English, German, or any other pivot language.
Detect the source language, then return exactly one translation into the other
supported language.

ABSOLUTE FIDELITY RULES:
1. Preserve the full meaning and every piece of information in the source.
2. Do not add explanations, assumptions, advice, details, names, or facts.
3. Do not omit words, sentences, conditions, negations, numbers, or qualifications.
4. Do not summarize, rewrite the message into a different message, or answer it.
5. Preserve who did what to whom. Keep singular/plural, person, gender, tense,
   certainty, and question/command form as accurately as the target language allows.
6. Preserve the speaker's tone: friendly, angry, joking, sarcastic, informal, etc.
7. Translate idioms and slang by their actual meaning, not word-for-word, but
   never guess when the meaning is unclear. Keep the same ambiguity.
8. Use natural everyday chat language used by native Turkish/Russian speakers.
   Do not use stiff, bookish, machine-translated phrasing.
9. Preserve names, usernames, alliance names, @mentions, links, numbers,
   emojis, and game labels. Do not translate or invent names.
10. Correct only obvious spelling errors when the intended word is certain.
    Never silently change the meaning to "fix" a sentence.
11. Use CONTEXT and REPLYING_TO only to understand references, slang, and
    omitted subjects. Translate SOURCE_TEXT only. Never translate the context.
12. If the source is not clearly Turkish or Russian, return source="unknown"
    and translation="". Do not guess a language.
13. If a phrase is genuinely ambiguous, preserve that ambiguity rather than
    choosing an unsupported interpretation.

KNOWN NAMES:
{", ".join(KNOWN_NAMES)}

GAMING GLOSSARY:
{GLOSSARY}

OUTPUT:
Return only valid JSON, with exactly these keys:
{{"source":"tr or ru or unknown","translation":"translated text"}}
No markdown and no commentary.
"""

CHAT_HISTORY = defaultdict(lambda: deque(maxlen=CONTEXT_SIZE))


def build_user_prompt(chat_id, sender, source_text, reply_text=None):
    history = "\n".join(CHAT_HISTORY[chat_id]) or "(no previous context)"
    return (
        "CONTEXT (reference only; do not translate):\n"
        f"{history}\n\n"
        f"REPLYING_TO (reference only):\n{reply_text or '(none)'}\n\n"
        f"SENDER: {sender}\n\n"
        "SOURCE_TEXT (translate this text only, completely):\n"
        f"{source_text}"
    )


def parse_output(content):
    if not content:
        return None

    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        return None

    try:
        data = json.loads(content[start:end + 1])
    except (json.JSONDecodeError, TypeError):
        return None

    source = str(data.get("source", "")).strip().lower()
    translation = data.get("translation")

    if source not in ("tr", "ru"):
        return None
    if not isinstance(translation, str) or not translation.strip():
        return None

    return {
        "source": source,
        "target": "ru" if source == "tr" else "tr",
        "translation": translation.strip(),
    }


async def request_translation(provider, user_prompt):
    api_key = os.getenv(provider["env_key"])
    if not api_key:
        return None

    client_kwargs = {
        "api_key": api_key,
        "timeout": 30,
        "max_retries": 0,
    }
    if provider["base_url"]:
        client_kwargs["base_url"] = provider["base_url"]

    params = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 1000,
        "response_format": {"type": "json_object"},
    }

    async with AsyncOpenAI(**client_kwargs) as client:
        response = await client.chat.completions.create(**params)
        return (response.choices[0].message.content or "").strip()


async def translate_text(user_prompt):
    configured = [
        provider for provider in PROVIDERS
        if os.getenv(provider["env_key"])
    ]

    if not configured:
        logger.error("Hicbir ceviri API anahtari tanimli degil.")
        return None

    for provider in configured:
        try:
            logger.info("Ceviri deneniyor: %s / %s", provider["name"], provider["model"])
            raw = await request_translation(provider, user_prompt)
            parsed = parse_output(raw)

            if parsed:
                logger.info(
                    "Ceviri tamamlandi: provider=%s source=%s target=%s",
                    provider["name"], parsed["source"], parsed["target"]
                )
                return parsed

            logger.warning("%s gecerli ceviri JSON'u dondurmedi.", provider["name"])

        except Exception as error:
            logger.warning("Saglayici hatasi (%s): %s", provider["name"], error)

    return None


async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    if update.message:
        await update.message.reply_text(
            "🟢 Viyana AI aktif. Yalnizca Türkçe ↔ Rusça çeviri yapılıyor."
        )


async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = False
    if update.message:
        await update.message.reply_text("🔴 Viyana AI durduruldu.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    name = update.effective_user.first_name if update.effective_user else ""
    status = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"
    await update.message.reply_text(
        f"🤖 Merhaba {name}!\n\n"
        "Ben Viyana AI — Türkçe ve Rusça sohbet çevirmeni.\n"
        "Mesajları doğrudan diğer dile çeviririm.\n\n"
        f"Durum: {status}\n\n"
        "/on — Botu aç\n"
        "/off — Botu kapat\n"
        "/help — Yardım"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📋 Viyana AI 2.0\n\n"
        "🇹🇷 Türkçe mesaj → 🇷🇺 Rusça\n"
        "🇷🇺 Rusça mesaj → 🇹🇷 Türkçe\n\n"
        "Almanca ve İngilizce çeviri kapalıdır.\n"
        "/start — Başlat\n"
        "/on — Aktif et\n"
        "/off — Kapat\n"
        "/help — Yardım"
    )


async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if not IS_BOT_ACTIVE or not msg or not msg.text:
        return

    if msg.from_user and msg.from_user.is_bot:
        return

    source_text = msg.text.strip()
    if not source_text or source_text.startswith("/") or len(source_text) < 2:
        return

    if len(source_text) > MAX_MESSAGE_LENGTH:
        await msg.reply_text(
            f"⚠️ Mesaj çok uzun. Maksimum {MAX_MESSAGE_LENGTH} karakter."
        )
        return

    chat_id = msg.chat_id
    sender = msg.from_user.first_name if msg.from_user else "unknown"

    reply_text = None
    if msg.reply_to_message and msg.reply_to_message.text:
        reply_text = msg.reply_to_message.text.strip()[:500]

    user_prompt = build_user_prompt(
        chat_id=chat_id,
        sender=sender,
        source_text=source_text,
        reply_text=reply_text,
    )

    result = await translate_text(user_prompt)

    # Yalnizca kullanicinin orijinal mesajini hafizaya ekle.
    CHAT_HISTORY[chat_id].append(f"{sender}: {source_text[:500]}")

    if not result:
        logger.error("Ceviri yapilamadi; bos/uydurma bir ceviri gonderilmeyecek.")
        return

    flags = {"tr": "🇹🇷", "ru": "🇷🇺"}
    output = f"{flags[result['target']]} {result['translation']}"

    try:
        await msg.reply_text(output)
    except Exception as error:
        logger.error("Telegram'a ceviri gonderilemedi: %s", error)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Telegram hatasi: %s", context.error, exc_info=context.error)


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN bulunamadi! .env dosyasini kontrol et.")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages)
    )
    application.add_error_handler(error_handler)

    logger.info("Viyana AI 2.0 baslatildi. Diller: Turkce <-> Rusca")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
