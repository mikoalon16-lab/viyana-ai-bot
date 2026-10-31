import os
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
# FAILOVER PROVIDERS (DOĞRULANMIŞ MODELLER)
# =========================================================

PROVIDERS = [
    {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-8b-instant",
    },
    {
        "name": "Gemini",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-1.5-flash",
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
        "name": "Cerebras",
        "env_key": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama3.1-8b",
    },
    {
        "name": "NVIDIA",
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.1-8b-instruct",
    },
]

# =========================================================
# SYSTEM PROMPT (ASCII/KLAVYE DÜZELTME VE DEYİM UYUMLU)
# =========================================================

SYSTEM_PROMPT = """
You are Viyana AI, a high-intelligence multi-lingual chat translation engine.

YOUR CORE RESPONSIBILITIES:
1. Detect the true source language of SOURCE_TEXT (among Turkish, Russian, German, English).
2. Translate the text ONLY into the remaining 3 target languages out of {TR, RU, DE, EN}.
3. DO NOT output a translation line for the detected source language (e.g., if input is Turkish, NEVER output TR).

CRITICAL INFORMAL & ASCII KEYBOARD HANDLING:
1. ASCII / ENGLISH KEYBOARD CORRECTION: Users often type with standard English keyboards missing native characters (e.g., Turkish written using 'u' for 'ü', 'c' for 'ç', 'g' for 'ğ', 's' for 'ş', 'i' for 'ı', 'o' for 'ö', or using chat shortcuts like 'bise', 'diyemice', 'nasil', 'yapiom'). You MUST mentally reconstruct the true intended words and grammar before translating.
2. IDIOMATIC & CONTEXTUAL TRANSLATION: NEVER perform literal word-for-word translations. Always capture the actual human intent, slang, chat metaphors, and humor.
   - Example: "ortaligi duman ediyordu" / "ortalığı duman ediyordu" -> EN: "he was tearing it up / blowing everyone away" (NOT "smoking up the place").
   - Example: "elin kizi" -> EN: "some random girl / a stranger's daughter".
   - Example: "sen nasil guzel bir insansin oyle kral" -> EN: "What an awesome person you are, absolute legend!"
3. PRESERVE ELEMENTS: Maintain all emojis, usernames (@user), links, codes, numbers, and original punctuation marks intact.
4. NO CHATBOT BEHAVIOR: Output ONLY the requested translation lines. Do not converse, comment, or write intros/outros.

OUTPUT FORMAT (Strictly output only lines for the remaining target languages):

TR: translation
RU: translation
DE: translation
EN: translation
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

async def translate_text(text):
    user_prompt = f"SOURCE_TEXT:\n{text}"

    content = None
    successful_provider = None

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
        return {}

    translations = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        code, value = line.split(":", 1)
        code = code.strip().lower()
        value = value.strip()

        if code in ["tr", "ru", "de", "en"] and value:
            translations[code] = value

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

    translations = await translate_text(text=text)

    if not translations:
        return

    flags = {"tr": "🇹🇷", "ru": "🇷🇺", "de": "🇩🇪", "en": "🇬🇧"}
    lines = []
    
    for lang in ["tr", "ru", "de", "en"]:
        if lang in translations:
            lines.append(f"{flags[lang]} {translations[lang]}")

    if lines:
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
