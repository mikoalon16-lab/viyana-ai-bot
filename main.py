import os
import time
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

# Sağlayıcı şablonları (Sırayla denenir)
PROVIDER_CONFIGS = [
    {
        "name": "Gemini",
        "env_prefixes": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
    },
    {
        "name": "Groq",
        "env_prefixes": ["GROQ_API_KEY"],
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
    {
        "name": "OpenAI",
        "env_prefixes": ["OPENAI_API_KEY"],
        "base_url": None,
        "model": "gpt-4.1-mini",
    },
    {
        "name": "Mistral",
        "env_prefixes": ["MISTRAL_API_KEY"],
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
    },
    {
        "name": "OpenRouter",
        "env_prefixes": ["OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.5-flash",
    },
    {
        "name": "DeepSeek",
        "env_prefixes": ["DEEPSEEK_API_KEY"],
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
]

# Kota/token biten anahtarları geçici olarak (600 sn) dinlendirmek için
COOLDOWN_UNTIL = {}
COOLDOWN_SECONDS = 600


def load_api_slots():
    """
    Render Dashboard'daki tüm anahtarları otomatik toplar.
    Örn: GEMINI_API_KEY, GEMINI_API_KEY_1, GEMINI_API_KEY_2 veya virgülle ayrılmış keyler.
    """
    slots = []
    seen_keys = set()

    for cfg in PROVIDER_CONFIGS:
        matched_vars = []
        for env_name, env_val in sorted(os.environ.items()):
            if not env_val or not env_val.strip():
                continue
            for prefix in cfg["env_prefixes"]:
                if env_name == prefix or env_name.startswith(prefix + "_"):
                    matched_vars.append((env_name, env_val.strip()))
                    break

        for env_name, raw_val in matched_vars:
            # Eğer tek değişkene virgülle birden fazla key yazıldıysa ayır
            parts = [k.strip() for k in raw_val.split(",") if k.strip()]
            for idx, key in enumerate(parts, start=1):
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                label = f"{cfg['name']} ({env_name}" + (f"#{idx})" if len(parts) > 1 else ")")
                slots.append({
                    "id": f"{cfg['name']}_{env_name}_{idx}",
                    "label": label,
                    "provider": cfg["name"],
                    "api_key": key,
                    "base_url": cfg["base_url"],
                    "model": cfg["model"],
                })
    return slots


API_SLOTS = load_api_slots()

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
3. NEVER output any other language.

ANTI-HALLUCINATION & STRICT ACCURACY RULES:
1. NEVER answer questions in SOURCE_TEXT. Translate the question; DO NOT answer it.
2. NEVER continue or complete an unfinished sentence. Translate only what is written.
3. NEVER add explanations, parentheses, notes, greetings, apologies, or extra words.
4. NEVER omit negations ("not", "değil", "не", "нет", "nicht", "kein"), numbers, times, conditions, or uncertainty.
5. Preserve exact subject-object relationships.
6. Understand gaming slang, abbreviations, and typos (e.g., "slm", "tmm", "nbr", "kanka", "спс", "пж", "хз", "бро", "digga", "alter", "gg", "afk") and translate their natural everyday chat equivalent.
7. Keep all proper names, nicknames, @mentions, links, numbers, and emojis untouched.
8. Use CONTEXT and REPLYING_TO strictly to resolve pronouns or ambiguous words. NEVER translate CONTEXT or REPLYING_TO.
9. If SOURCE_TEXT is gibberish, just emojis/symbols, a single random letter, or an unsupported language, return:
   {{"source":"unknown","translations":{{}}}}

KNOWN NAMES (DO NOT TRANSLATE):
{", ".join(KNOWN_NAMES)}

GAMING GLOSSARY:
{GLOSSARY}

STRICT JSON OUTPUT FORMAT:
Return ONLY a raw JSON object with no markdown blocks or extra text:
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
    if set(raw_translations.keys()) != set(target_langs):
        return None

    translations = {}
    src_len = max(len(source_text.strip()), 1)

    for lang in target_langs:
        text = raw_translations.get(lang)
        if not isinstance(text, str) or not text.strip():
            return None

        cleaned = text.strip()
        if len(cleaned) > max(src_len * 4, 140):
            logger.warning("Uydurma/uzun ceviri engellendi (%s): %s", lang, cleaned[:80])
            return None

        translations[lang] = cleaned

    return {
        "source": source,
        "translations": translations,
    }


async def request_translation(slot, user_prompt):
    client_kwargs = {
        "api_key": slot["api_key"],
        "timeout": 20,
        "max_retries": 0,
    }
    if slot["base_url"]:
        client_kwargs["base_url"] = slot["base_url"]

    params = {
        "model": slot["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "top_p": 0.1,
        "max_tokens": 1500,
    }

    # Bazı OpenAI uyumlu sağlayıcılarda response_format hatasını önlemek için:
    if slot["provider"] in ("Gemini", "OpenAI", "Mistral", "Groq"):
        params["response_format"] = {"type": "json_object"}

    async with AsyncOpenAI(**client_kwargs) as client:
        response = await client.chat.completions.create(**params)
        content = response.choices[0].message.content
        return content.strip() if content else ""


async def translate_text(user_prompt, source_text):
    if not API_SLOTS:
        logger.error("HICBIR API ANAHTARI BULUNAMADI! Render Environment Variables kontrol et.")
        return None

    now = time.time()
    # Önce dinlendirmede olmayan aktif anahtarları dene; hepsi dinlendirmedeyse yine de sıradan dene
    active_slots = [s for s in API_SLOTS if COOLDOWN_UNTIL.get(s["id"], 0) <= now]
    candidates = active_slots if active_slots else API_SLOTS

    for slot in candidates:
        try:
            logger.info("Deneniyor -> %s | Model: %s", slot["label"], slot["model"])
            raw = await request_translation(slot, user_prompt)
            parsed = parse_output(raw, source_text)

            if parsed:
                # Başarılı olursa varsa cooldown'u temizle
                COOLDOWN_UNTIL.pop(slot["id"], None)
                logger.info(
                    "BASARILI -> %s | %s -> %s",
                    slot["label"],
                    parsed["source"],
                    ",".join(parsed["translations"].keys()),
                )
                return parsed

            logger.warning("%s gecerli JSON dondurmedi, siradakine geciliyor...", slot["label"])

        except Exception as error:
            err_str = str(error).lower()
            is_quota_or_auth = any(
                code in err_str
                for code in ("429", "401", "402", "403", "quota", "rate limit", "insufficient", "credit", "billing", "exceeded", "invalid_api_key")
            )
            if is_quota_or_auth:
                COOLDOWN_UNTIL[slot["id"]] = time.time() + COOLDOWN_SECONDS
                logger.warning(
                    "TOKEN/KOTA DOLU VEYA GECERSIZ (%s) -> 10 dk pasife alindi, siradakine geciliyor! Detay: %s",
                    slot["label"],
                    error,
                )
            else:
                logger.warning("Baglanti/API hatasi (%s) -> siradakine geciliyor: %s", slot["label"], error)

    logger.error("TUM API ANAHTARLARI DENENDI AMA CEVIRI ALINAMADI!")
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


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    now = time.time()
    lines = [f"📊 Yüklü API Sayısı: {len(API_SLOTS)}"]
    for s in API_SLOTS:
        wait = int(COOLDOWN_UNTIL.get(s["id"], 0) - now)
        state = f"⏳ Dinlenmede ({wait}s)" if wait > 0 else "✅ Hazır"
        lines.append(f"• {s['label']} -> {state}")
    await update.message.reply_text("\n".join(lines))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    name = update.effective_user.first_name if update.effective_user else ""
    status = "🟢 Aktif" if IS_BOT_ACTIVE else "🔴 Kapalı"
    await update.message.reply_text(
        f"🤖 Merhaba {name}!\n\n"
        "Ben Viyana AI — Türkçe, Rusça, Almanca ve İngilizce sohbet çevirmeni.\n\n"
        f"Durum: {status} | Aktif API Slot: {len(API_SLOTS)}\n\n"
        "/on — Botu aç\n"
        "/off — Botu kapat\n"
        "/status — API durumlarını gör\n"
        "/help — Yardım"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "📋 Viyana AI 2.4\n\n"
        "🇹🇷 Türkçe ↔ 🇷🇺 Rusça ↔ 🇩🇪 Almanca ↔ 🇬🇧 İngilizce\n\n"
        "/start — Başlat\n"
        "/on — Aktif et\n"
        "/off — Kapat\n"
        "/status — API anahtarlarını kontrol et"
    )


async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    logger.info("Mesaj alindi [chat=%s]: %s", msg.chat_id, msg.text[:40])

    if not IS_BOT_ACTIVE:
        return

    if msg.from_user and msg.from_user.is_bot:
        return

    source_text = msg.text.strip()
    if not source_text or source_text.startswith("/") or len(source_text) < 2:
        return

    if not any(ch.isalpha() for ch in source_text):
        return

    if len(source_text) > MAX_MESSAGE_LENGTH:
        await msg.reply_text(f"⚠️ Mesaj çok uzun. Maksimum {MAX_MESSAGE_LENGTH} karakter.")
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
    CHAT_HISTORY[chat_id].append(f"{sender}: {source_text[:500]}")

    if not result:
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
        logger.error("TELEGRAM_BOT_TOKEN bulunamadi! Render Environment ayarini kontrol et.")
        return

    logger.info("Viyana AI 2.4 baslatiliyor... Bulunan API anahtari sayisi: %d", len(API_SLOTS))
    for slot in API_SLOTS:
        logger.info(" -> Yuklenen API: %s", slot["label"])

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("on", on_command))
    application.add_handler(CommandHandler("off", off_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages)
    )
    application.add_error_handler(error_handler)

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
