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

# Yalnizca guclu ve yuksek dogruluklu modeller.
# Bir saglayici hata verirse veya sacmalarsa siradakine gecilir.
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

# Cevrilmemesi gereken kisi, ittifak ve oyuncu adlari.
KNOWN_NAMES = [
    "Ehed",
    "Əhəd",
    "Fırat",
    "Viyana",
    "Unprincipled",
    "Dark Legion",
    "Akıncılar",
    "Göktürkler",
    "Şahin",
]

GLOSSARY = """
Oyun ve sohbet baglami icin kesin terim karsiliklari (TR / RU / DE / EN):
- taht (taç degil) / трон / Thron / throne
- sunucular arasi savas (kvk / svs) / межсерверная битва / Server-übergreifender Krieg / cross-server war
- ittifak / альянс / Allianz / alliance
- bolge / регион / Region / region
- lider / лидер / Anführer / leader
- elmaslar / алмазы / Diamanten / diamonds
- taht sirasi / очередь за троном / Thron-Reihenfolge / throne rotation
- vezir / визирь / Wesir / vizier
- etkinlik / событие (ивент) / Event / event
- puan / очки / Punkte / points
- sandik / сундук / Truhe / chest
- saldiri / атака / Angriff / attack
- savunma / защита / Verteidigung / defense
Terimleri yalnizca mesaj oyun veya sohbet baglamindaysa kullan. Kaynakta olmayan hicbir bilgi ekleme.
"""

SYSTEM_PROMPT = f"""
You are Viyana AI, a strictly literal and accurate Turkish-Russian-German-English chat translator for a gaming community.

SUPPORTED LANGUAGES ONLY:
- Turkish ("tr")
- Russian ("ru")
- German ("de")
- English ("en")

CORE TASK:
1. Identify the exact language of SOURCE_TEXT ("tr", "ru", "de", or "en").
2. Translate ONLY SOURCE_TEXT into the OTHER THREE supported languages.
3. NEVER output any other language (no Azerbaijani unless identical to Turkish loanwords, no Arabic, no Spanish, no French).

ANTI-HALLUCINATION & STRICT ACCURACY RULES:
1. NEVER answer questions in SOURCE_TEXT. If the user asks "What time is the war?", translate the question; DO NOT answer it.
2. NEVER continue or complete an unfinished sentence. Translate only what is written.
3. NEVER add explanations, parentheses, notes, greetings, apologies, or extra words that do not exist in SOURCE_TEXT.
4. NEVER omit negations ("not", "değil", "не", "нет", "nicht", "kein"), numbers, times, conditions ("if", "eğer", "если", "wenn"), or uncertainty ("maybe", "belki", "может быть", "vielleicht").
5. Preserve exact subject-object relationships (who is attacking whom, who is giving what to whom).
6. Understand gaming slang, abbreviations, and typos (e.g., "slm", "tmm", "nbr", "kanka", "спс", "пж", "хз", "бро", "digga", "alter", "gg", "afk") and translate their natural everyday chat equivalent without inventing extra meaning.
7. Keep all proper names, nicknames, @mentions, links, numbers, and emojis untouched. Do not translate names like "Şahin" (hawk) or "Viyana" (Vienna) when used as player/alliance names.
8. Use CONTEXT and REPLYING_TO strictly to resolve pronouns ("o", "bunu", "это", "das", "it") or ambiguous words. NEVER translate CONTEXT or REPLYING_TO.
9. If SOURCE_TEXT is gibberish, just emojis/symbols, a single random letter, or a language other than Turkish/Russian/German/English, return:
   {{"source":"unknown","translations":{{}}}}

KNOWN NAMES (DO NOT TRANSLATE):
{", ".join(KNOWN_NAMES)}

GAMING GLOSSARY:
{GLOSSARY}

STRICT JSON OUTPUT FORMAT:
Return ONLY a raw JSON object with no markdown blocks, no backticks, and no extra text:
{{"source":"tr|ru|de|en|unknown","translations":{{"lang1":"exact translation 1","lang2":"exact translation 2","lang3":"exact translation 3"}}}}
"""

SUPPORTED_LANGS = ("tr", "ru", "de", "en")
LANG_FLAGS = {
    "tr": "🇹🇷",
    "ru": "🇷🇺",
    "de": "🇩🇪",
    "en": "🇬🇧",
}

CHAT_HISTORY = defaultdict(lambda: deque(maxlen=CONTEXT_SIZE))


def build_user_prompt(chat_id, sender, source_text, reply_text=None):
    history = "\n".join(CHAT_HISTORY[chat_id]) or "(no previous context)"
    return (
        "CONTEXT (reference only; DO NOT translate):\n"
        f"{history}\n\n"
        f"REPLYING_TO (reference only; DO NOT translate):\n{reply_text or '(none)'}\n\n"
        f"SENDER: {sender}\n\n"
        "SOURCE_TEXT (translate ONLY this text accurately):\n"
        f"{source_text}"
    )


def parse_output(content, source_text):
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
    raw_translations = data.get("translations")

    if source not in SUPPORTED_LANGS or not isinstance(raw_translations, dict):
        return None

    target_langs = [lang for lang in SUPPORTED_LANGS if lang != source]

    # Tam olarak diger 3 hedef dil mevcut olmali, fazla veya eksik anahtar varsa reddet
    if set(raw_translations.keys()) != set(target_langs):
        return None

    translations = {}
    src_len = max(len(source_text.strip()), 1)

    for lang in target_langs:
        text = raw_translations.get(lang)
        if not isinstance(text, str) or not text.strip():
            return None

        cleaned = text.strip()

        # Halusinasyon / uydurma uzunluk kontrolu:
        # Kisa bir mesaja paragraflar dolusu aciklama uydurursa reddet.
        if len(cleaned) > max(src_len * 4, 140):
            logger.warning("Uydurma/uzun ceviri engellendi (%s): %s", lang, cleaned[:80])
            return None

        translations[lang] = cleaned

    return {
        "source": source,
        "translations": translations,
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
        "temperature": 0.0,
        "top_p": 0.1,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }

    async with AsyncOpenAI(**client_kwargs) as client:
        response = await client.chat.completions.create(**params)
        content = response.choices[0].message.content
        if content:
            return content.strip()
        return ""


async def translate_text(user_prompt, source_text):
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
            parsed = parse_output(raw, source_text)

            if parsed:
                targets = ",".join(parsed["translations"].keys())
                logger.info(
                    "Ceviri tamamlandi: provider=%s source=%s targets=%s",
                    provider["name"], parsed["source"], targets
                )
                return parsed

            logger.warning("%s gecerli/guvenli ceviri JSON'u dondurmedi.", provider["name"])

        except Exception as error:
            logger.warning("Saglayici hatasi (%s): %s", provider["name"], error)

    return None


async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    if update.message:
        await update.message.reply_text(
            "🟢 Viyana AI aktif. Türkçe ↔ Rusça ↔ Almanca ↔ İngilizce çeviri yapılıyor."
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
        "Ben Viyana AI — Türkçe, Rusça, Almanca ve İngilizce sohbet çevirmeni.\n"
        "Mesajları otomatik olarak diğer üç dile çeviririm.\n\n"
        f"Durum: {status}\n\n"
        "/on — Botu aç\n"
        "/off — Botu kapat\n"
        "/help — Yardım"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📋 Viyana AI 2.3\n\n"
        "🇹🇷 Türkçe → 🇷🇺 Rusça + 🇩🇪 Almanca + 🇬🇧 İngilizce\n"
        "🇷🇺 Rusça → 🇹🇷 Türkçe + 🇩🇪 Almanca + 🇬🇧 İngilizce\n"
        "🇩🇪 Almanca → 🇹🇷 Türkçe + 🇷🇺 Rusça + 🇬🇧 İngilizce\n"
        "🇬🇧 İngilizce → 🇹🇷 Türkçe + 🇷🇺 Rusça + 🇩🇪 Almanca\n\n"
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

    # Sadece rakam veya noktalama isaretlerinden olusan mesajlari cevirme
    if not any(ch.isalpha() for ch in source_text):
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

    result = await translate_text(user_prompt, source_text)

    # Yalnizca kullanicinin orijinal mesajini hafizaya ekle.
    CHAT_HISTORY[chat_id].append(f"{sender}: {source_text[:500]}")

    if not result:
        logger.info("Mesaj cevrilmedi (desteklenmeyen dil, anlamsiz metin veya saglayici hatasi).")
        return

    lines = [
        f"{LANG_FLAGS[lang]} {text}"
        for lang, text in result["translations"].items()
    ]
    output = "\n".join(lines)

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

    logger.info("Viyana AI 2.3 baslatildi. Diller: Turkce <-> Rusca <-> Almanca <-> Ingilizce")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
