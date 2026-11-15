# =========================================================
# VİYANA AI - ÇOK DİLLİ ÇEVİRİ BOTU (KALİTE GÜNCELLEMESİ)
# Değişenler: JSON çıktı, sohbet bağlamı, reply bağlamı, isim koruma,
# sözlük, daha iyi sağlayıcı sırası, bot mesajlarını yok sayma.
# =========================================================

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
CONTEXT_SIZE = 8  # her sohbetten hatırlanan son mesaj sayısı
IS_BOT_ACTIVE = True

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("viyana_ai")

# =========================================================
# SAĞLAYICILAR (en kaliteliden en zayıfa)
# json=True: sağlayıcı response_format=json_object destekliyor
# NOT: Model adlarını kendi hesabında geçerli olanla kontrol et.
# =========================================================

PROVIDERS = [
    {
        "name": "Gemini",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "json": True,
    },
    {
        "name": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-4.1-mini",
        "json": True,
    },
    {
        "name": "Mistral",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "json": True,
    },
    {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "json": True,
    },
    # Aşağıdakiler 8B model: Türkçe/Rusça kalitesi düşük, sadece son çare.
    {
        "name": "Cerebras",
        "env_key": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama3.1-8b",
        "json": False,
    },
    {
        "name": "NVIDIA",
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-8b-instruct",
        "json": False,
    },
]

# =========================================================
# İSİMLER VE SÖZLÜK  (kendi topluluğuna göre doldur)
# =========================================================

KNOWN_NAMES = ["Ehed", "Fırat", "Viyana"]  # çevrilmemesi gereken isimler

GLOSSARY = """
- Ehed = person name (Cyrillic: Ехед). Never a verb. Same for every name in KNOWN_NAMES.
- "atmak" in chat Turkish usually means to send/post/drop a message, file or link ("Onlara attım" = I sent it to them), not to physically throw.
- "direk/direkt" = directly, straight away.
- "sapıtmak", "zıvanadan çıkmak" = to go crazy / off the rails (only if the context fits).
- "ayar çekmek" = to give someone a talking-to (only if the context fits).
- "ittifak" = alliance, "bölge" = region/zone, "lider" = leader (strategy game community).
"""

# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = f"""
You translate chat messages of a Turkish/Russian/German/English gaming community.
Your job is to produce what a bilingual native speaker would write to say the SAME thing in a chat. Be faithful first, natural second.

STEPS (follow in order, internally):
1. Detect the source language of SOURCE_TEXT: tr, ru, de or en.
2. Work out what the speaker really means (use CONTEXT and REPLYING_TO to resolve slang, pronouns and ellipsis). Write this as one short English sentence in "meaning".
3. Translate that meaning into the other three languages only.

STRICT RULES:
- FAITHFUL: do not add, remove or soften information. Do not add words like "I can say", "it seems", "I think" unless the speaker said them. Never invent content.
- Keep person, number and gender exactly: "он" = he (not they), "ты" = you (singular), etc.
- NOT LITERAL: translate meaning, not words. Use the idiom a native would use in chat.
- NAMES: never translate names or usernames. Names written in Cyrillic (e.g. Ехед) are the same person as the Latin form (Ehed): write Latin in tr/de/en and Cyrillic in ru. Known names: {", ".join(KNOWN_NAMES)}.
- If the source text is truly ambiguous, keep it equally ambiguous in the translation. Do not guess a more specific meaning.
- Fix obvious typos/missing diacritics silently (ASCII Turkish: u->ü, c->ç, s->ş, g->ğ, i->ı).
- Keep emojis, @mentions, links, numbers, game terms and tone (sarcasm, jokes, anger) as they are.
- Do not copy phrases from these instructions into your answer. Translate only SOURCE_TEXT.

GLOSSARY:
{GLOSSARY}

OUTPUT: only a JSON object, no markdown, no extra text:
{{"source": "tr|ru|de|en", "meaning": "...", "tr": "...", "ru": "...", "de": "...", "en": "..."}}
Omit the key of the source language. Do not output anything else.
"""

# =========================================================
# BAĞLAM HAFIZASI
# =========================================================

CHAT_HISTORY = defaultdict(lambda: deque(maxlen=CONTEXT_SIZE))


def build_user_prompt(chat_id, sender, text, reply_text):
    history = "\n".join(CHAT_HISTORY[chat_id]) or "(none)"
    parts = [
        f"CONTEXT (recent messages, oldest first):\n{history}",
        f"REPLYING_TO: {reply_text}" if reply_text else "REPLYING_TO: (none)",
        f"SENDER: {sender}",
        f"SOURCE_TEXT:\n{text}",
    ]
    return "\n\n".join(parts)


# =========================================================
# ÇEVİRİ
# =========================================================

TARGETS = ["tr", "ru", "de", "en"]


def parse_output(content):
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None

    source = str(data.get("source", "")).lower().strip()
    result = {}
    for lang in TARGETS:
        value = data.get(lang)
        if lang != source and isinstance(value, str) and value.strip():
            result[lang] = value.strip()

    # kaynak dil hariç 3 çevirinin de gelmesi lazım
    if len(result) < 3:
        return None
    return result


async def request_translation(provider, user_prompt):
    api_key = os.getenv(provider["env_key"])
    if not api_key:
        return None

    kwargs = {"api_key": api_key, "timeout": 20, "max_retries": 0}
    if provider["base_url"]:
        kwargs["base_url"] = provider["base_url"]

    params = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    if provider["json"]:
        params["response_format"] = {"type": "json_object"}

    async with AsyncOpenAI(**kwargs) as client:
        response = await client.chat.completions.create(**params)
        return (response.choices[0].message.content or "").strip()


async def translate_text(user_prompt):
    for provider in PROVIDERS:
        try:
            logger.info("Çeviri deneniyor provider=%s", provider["name"])
            raw = await request_translation(provider, user_prompt)
            if not raw:
                continue
            parsed = parse_output(raw)
            if parsed:
                logger.info("Çeviri tamam via %s", provider["name"])
                return parsed
            logger.warning("%s geçersiz format döndürdü, sıradaki deneniyor", provider["name"])
        except Exception as error:
            logger.warning("Provider %s başarısız: %s", provider["name"], error)
    return {}


# =========================================================
# KOMUTLAR
# =========================================================

async def on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = True
    if update.message:
        await update.message.reply_text("🟢 Bot aktif edildi. Otomatik çeviri çalışıyor.")


async def off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BOT_ACTIVE
    IS_BOT_ACTIVE = False
    if update.message:
        await update.message.reply_text("🔴 Bot kapatıldı.")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    name = update.effective_user.first_name if update.effective_user else ""
    status_str = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"
    await update.message.reply_text(
        f"🤖 Merhaba {name}!\n\n"
        f"Ben Viyana AI — otomatik çoklu dil çeviri botuyum.\n"
        f"Ehed tarafından tasarlandım.\n\n"
        f"Durum: {status_str}\n\n"
        f"/on — Botu açar\n/off — Botu kapatır\n/help — Yardım"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📋 Viyana AI Yardım\n\n"
        "Mesajları otomatik algılar ve diğer dillere (TR, RU, DE, EN) doğal şekilde çevirir.\n\n"
        "/start — Başlat\n/on — Aktif Et\n/off — Kapat\n/help — Yardım"
    )


# =========================================================
# MESAJ İŞLEME
# =========================================================

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not IS_BOT_ACTIVE or not msg or not msg.text:
        return
    # botların mesajlarını (kendi çevirileri dahil) çevirme
    if msg.from_user and msg.from_user.is_bot:
        return

    text = msg.text.strip()
    if not text or text.startswith("/") or len(text) < 2:
        return
    if len(text) > MAX_MESSAGE_LENGTH:
        await msg.reply_text(f"⚠️ Mesaj çok uzun. Maksimum {MAX_MESSAGE_LENGTH} karakter.")
        return

    chat_id = msg.chat_id
    sender = msg.from_user.first_name if msg.from_user else "unknown"

    reply_text = None
    if msg.reply_to_message and msg.reply_to_message.text:
        # bot çevirisine cevap verilmişse sadece ilk satırı al (ilk dil satırı yeterli)
        reply_text = msg.reply_to_message.text.strip()[:300]

    user_prompt = build_user_prompt(chat_id, sender, text, reply_text)
    translations = await translate_text(user_prompt)

    # kaynak mesajı bağlama ekle (çeviri başarısız olsa da)
    CHAT_HISTORY[chat_id].append(f"{sender}: {text[:300]}")

    if not translations:
        return

    flags = {"tr": "🇹🇷", "ru": "🇷🇺", "de": "🇩🇪", "en": "🇬🇧"}
    lines = [f"{flags[lang]} {translations[lang]}" for lang in TARGETS if lang in translations]
    if lines:
        await msg.reply_text("\n\n".join(lines))


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

    logger.info("Viyana AI başlatıldı.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
