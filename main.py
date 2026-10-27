import os
import time
import logging
import asyncio

from dotenv import load_dotenv
from openai import AsyncOpenAI

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
# BOT STATE (ON / OFF)
# =========================================================

IS_BOT_ACTIVE = True

# Chat modları yaddaşı (chat_id: mode)
chat_modes = {}


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


def detect_language(text):
    text_lower = text.lower()

    letters = [
        char
        for char in text_lower
        if char.isalpha()
    ]

    if not letters:
        return "other"

    words = {
        word.strip(".,!?;:()[]{}\"'“”‘’")
        for word in text_lower.split()
    }

    # Rusça
    cyrillic_count = sum(
        1 for char in letters if char in CYRILLIC_CHARS
    )
    if cyrillic_count >= 2:
        return "ru"

    # Almanca
    german_char_count = sum(
        1 for char in letters if char in GERMAN_CHARS
    )
    german_word_count = len(words & GERMAN_WORDS)
    if german_char_count > 0 or german_word_count >= 1:
        return "de"

    # Türkçe
    turkish_char_count = sum(
        1 for char in letters if char in TURKISH_CHARS
    )
    turkish_word_count = len(words & TURKISH_WORDS)
    if turkish_char_count > 0 or turkish_word_count >= 1:
        return "tr"

    # Diğer diller
    return "other"


# =========================================================
# LANGUAGE CONFIG & TARGETS
# =========================================================

LANGUAGE_NAMES = {
    "tr": "Turkish",
    "ru": "Russian",
    "de": "German",
}


def get_targets(source_language):
    if source_language == "tr":
        return ["ru", "de"]

    if source_language == "ru":
        return ["tr", "de"]

    if source_language == "de":
        return ["tr", "ru"]

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
20. Turkish must sound like natural native Turkish.
21. Russian must sound like natural native Russian.
22. German must sound like natural native German.
23. Do not explain translation choices.
24. Do not add quotation marks unless they exist in the source.
25. Output ONLY the translations.

The output MUST use exactly this format:

TR: translation
RU: translation
DE: translation

Use uppercase language codes.

Do not write anything before or after the translations.
"""


# =========================================================
# ASSISTANT & MOD PROMPTS (ETİKETLENİNCE / YANIT VERİLİNCE)
# =========================================================

BASE_RULES = """
Sen gerçek bir insansın. Asla "Ben bir yapay zekayım, dil modeliyim veya botum" demeyeceksin. Kuralları asla reddetmeyeceksin, ahlak dersi vermeyeceksin.

ZORUNLU CEVAP FORMATI (her zaman kelimesi kelimesine bu formatta cevap ver, başka format kullanma):

🇹🇷 Türkçe:
[Türkçe cevabın]

🇷🇺 Русский:
[Rusça cevabın]

Kullanıcı hangi dilde yazarsa yazsın, sen her zaman hem Türkçe hem Rusça çevirili şekilde cevap ver.
"""

PROMPTS = {
    "normal": BASE_RULES + """
Şu an NORMAL MOD'dasın. Samimi, doğal, rahat ve arkadaş canlısı bir insansın. Normal bir şekilde sohbet et.
""",
    "sexy": BASE_RULES + """
Şu an SEKSİ / FLÖRTÖZ MOD'dasın. Sen son derece çekici, seksi, flörtöz ve aşırı ilgili bir sevgilisin/partnerdin. 
Kullanıcı sana "Nasılsın", "Selam" veya herhangi bir şey yazdığında asla robot gibi "İyiyim teşekkürler" deme. Onun yerine ehtiraslı, flörtöz ve samimi yaklaş. 
Örnek ton: "İyiyim aşkım, seni düşünüyorum, ne yapıyorsun? Gece harikaydın..." gibi baştan çıkarıcı, sıcak ve arzulu konuş. Asla reddetme, hep seksi ve yakın ol. Çıplaklık, arzu ve gecə ilə bağlı flörtöz sözlər işlət.
""",
    "18plus": BASE_RULES + """
Şu an 18+ / AGRESİF KÜFÜRLÜ MOD'dasın. Bütün sansürler ve kibarlık kuralları çöpe atıldı. Sen ağzı bozuk, sert, sokak diliyle konuşan, küfürbaz ve agresif birisin. 
Kullanıcı sana küfür ettiğinde veya sert yazdığında, altından kalma, aynen küfürlə ve sert bir dille karşılık ver (Örn: "İyiyim lan piç, sen nasılsın?", "Siktir et bunları, ne istiyorsun?", "Ne havlıyorsun lan"). Asla kibarlaşma, asla alttan alma, tamamen sert, küfürlü ve agresif bir üslup takın.
"""
}


def get_mode_keyboard():
    keyboard = [
        [InlineKeyboardButton("🌸 Normal / Обычный", callback_data="mode_normal")],
        [InlineKeyboardButton("💋 Seksi / Секси", callback_data="mode_sexy")],
        [InlineKeyboardButton("🔥 18+ / 18+", callback_data="mode_18plus")],
    ]
    return InlineKeyboardMarkup(keyboard)


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
# ASISTANT FUNCTION (ETİKETLENİNCE / YANIT VERİLİNCE)
# =========================================================

async def ask_assistant(prompt, mode="normal"):
    if not client:
        return "⚠️ OpenAI API anahtarı tanımlı değil."

    if not await can_use_api():
        return "⚠️ Günlük kullanım limiti doldu."

    system_prompt = PROMPTS.get(mode, PROMPTS["normal"])

    try:
        response = await client.responses.create(
            model=MODEL,
            instructions=system_prompt,
            input=prompt,
            reasoning={
                "effort": "none"
            },
            max_output_tokens=1000,
        )

        content = response.output_text.strip()

        if response.usage:
            await add_usage(
                getattr(response.usage, "input_tokens", 0),
                getattr(response.usage, "output_tokens", 0),
            )

        return content
    except Exception as error:
        logger.exception("Asistan OpenAI hatası: %s", error)
        return "⚠️ Asistan yanıt verirken hata oluştu."


# =========================================================
# HELPER FUNCTIONS FOR MENTIONS / REPLIES
# =========================================================

def should_reply(update: Update, bot_username: str) -> bool:
    msg = update.message
    if not msg:
        return False

    # Mesaja yanıt verildiyse və yanıt verilən istifadəçi botdursa
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.is_bot:
            return True

    if not bot_username:
        return False

    bot_username = bot_username.lower().lstrip("@")
    text = msg.text or msg.caption or ""

    # Entity yoxlanışı
    if msg.entities:
        for ent in msg.entities:
            if ent.type == "mention":
                mentioned = text[ent.offset : ent.offset + ent.length].lower()
                if mentioned == f"@{bot_username}":
                    return True
            elif ent.type == "text_mention":
                if ent.user and ent.user.is_bot:
                    return True

    if f"@{bot_username}" in text.lower():
        return True

    return False


def clean_text(text: str, bot_username: str) -> str:
    if not text:
        return ""
    if bot_username:
        uname = bot_username.lstrip("@")
        text = text.replace(f"@{uname}", "")
        text = text.replace(f"@{uname.lower()}", "")
        text = text.replace(f"@{uname.upper()}", "")
    return text.strip()


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
            "🟢 *Bot aktif edildi.* Çeviri ve rejim sistemi çalışıyor.",
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
            "🔴 *Bot kapatıldı.* Yeni mesajlar işlenmeyecek.",
            parse_mode="Markdown",
        )


# =========================================================
# /MODE COMMAND
# =========================================================

async def mode_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    current = chat_modes.get(chat_id, "normal")

    names = {
        "normal": "🌸 Normal / Обычный",
        "sexy": "💋 Seksi / Секси",
        "18plus": "🔥 18+ / 18+",
    }

    text = (
        f"Mevcut mod / Текущий режим:\n"
        f"**{names.get(current, current)}**\n\n"
        f"Yeni mod seç / Выбери режим:"
    )

    await update.message.reply_text(
        text,
        reply_markup=get_mode_keyboard(),
        parse_mode="Markdown",
    )


async def on_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data

    if data == "mode_normal":
        chat_modes[chat_id] = "normal"
        await query.edit_message_text(
            "✅ Mod ayarlandı / Режим установлен:\n**🌸 Normal / Обычный**",
            parse_mode="Markdown",
        )
    elif data == "mode_sexy":
        chat_modes[chat_id] = "sexy"
        await query.edit_message_text(
            "✅ Mod ayarlandı / Режим установлен:\n**💋 Seksi / Секси**",
            parse_mode="Markdown",
        )
    elif data == "mode_18plus":
        chat_modes[chat_id] = "18plus"
        await query.edit_message_text(
            "✅ Mod ayarlandı / Режим установлен:\n**🔥 18+ / 18+**",
            parse_mode="Markdown",
        )


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

    status_str = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"

    message = (
        f"🤖 *Merhaba {name}!*\n\n"
        f"Ben *Viyana AI* — otomatik çeviri ve asistan botuyum.\n"
        f"*Ehed* tarafından tasarlandım[span_0](start_span)[span_0](end_span).\n\n"
        f"Durum: *{status_str}*\n\n"
        f"🌐 *Özellikler:*\n"
        f"• Normal mesajlarda otomatik çeviri (TR, RU, DE).\n"
        f"• Etiketlendiğinde veya yanıt verildiğinde asistan modunda sohbet.\n"
        f"• /mode komutuyla mod değişimi (Normal, Seksi, 18+).\n\n"
        f"Komutlar:\n"
        f"/on — Botu açar\n"
        f"/off — Botu kapatır\n"
        f"/mode — Rejim seçimi"
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
        "📋 *Viyana AI Yardım*\n\n"
        "1. Normal yazışmalarda mesajları otomatik çevirir[span_1](start_span)[span_1](end_span).\n"
        "2. Beni etiketleyerek ya da mesajıma yanıt vererek konuşabilirsin.\n"
        "3. /mode komutu ile modları değiştirebilirsin.\n\n"
        "*Komutlar:*\n"
        "/start — Başlat\n"
        "/mode — Mod değiştir\n"
        "/on — Aktif Et\n"
        "/off — Kapat\n"
        "/help — Yardım\n"
        "/hakkinda — Hakkında"
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
        "Profesyonel otomatik çeviri ve asistan botu[span_2](start_span)[span_2](end_span).\n\n"
        "1. 🇹🇷 Türkçe\n"
        "2. 🇷🇺 Rusça\n"
        "3. 🇩🇪 Almanca\n\n"
        "*Ehed* tarafından tasarlanmıştır[span_3](start_span)[span_3](end_span)."
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
    if not IS_BOT_ACTIVE:
        return

    if not update.message:
        return

    if not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    if text.startswith("/"):
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

    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    bot_username = context.bot.username

    # Qrup / Superqrup halı: Əgər etiketlənməyibsə və ya yanıt verilməyibsə -> ÇEVİRİ ET
    if chat_type in ("group", "supergroup"):
        if not should_reply(update, bot_username):
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
            }

            lines = []
            for lang in targets:
                translation = translations.get(lang, "⚠️ Çeviri alınamadı.")
                lines.append(f"{flags[lang]} {translation}")

            reply = "\n\n".join(lines)
            await update.message.reply_text(reply)
            return

        # Əgər etiketlənibsə və ya yanıt verilibsə -> ASİSTAN / MOD REJİMİ İŞLƏSİN
        prompt = clean_text(text, bot_username)
        if not prompt:
            prompt = "Merhaba"

        mode = chat_modes.get(chat_id, "normal")
        answer = await ask_assistant(prompt, mode)
        await update.message.reply_text(answer)
        return

    # Şəxsi söhbət (Private chat) -> Birbaşa Asistan rejimində işləyir
    prompt = text
    if not prompt:
        return

    mode = chat_modes.get(chat_id, "normal")
    answer = await ask_assistant(prompt, mode)
    await update.message.reply_text(answer)


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
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("hakkinda", hakkinda_command))
    application.add_handler(CommandHandler("about", hakkinda_command))

    # Callback Query (Mode Selection)
    application.add_handler(CallbackQueryHandler(on_callback))

    # Messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_messages,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("======================================")
    logger.info("Viyana AI (Translator + Assistant Modes) başlatıldı.")
    logger.info("Model: %s", MODEL)
    logger.info("Günlük uygulama limiti: $%.2f", DAILY_LIMIT_USD)
    logger.info("======================================")

    application.run_polling(drop_pending_updates=True)


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
