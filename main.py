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

# Yalnizca guclu/orta seviye modeller.
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
KNOWN_NAMES = [
    "Ehed",
    "Fırat",
    "Viyana",
    "Unprincipled",
]

GLOSSARY = """
Oyun baglami icin terim tercihleri (TR / DE / EN):
- taht (taç degil) / Thron / throne
- sunucular arasi savas / Server-übergreifender Krieg (Kampf) / cross-server war (battle)
- ittifak / Allianz / alliance
- bolge / Region (Gebiet) / region (territory)
- lider / Anführer (Leiter) / leader
- elmaslar / Diamanten / diamonds
- taht sirasi (tahta cikma sirasi) / Thron-Warteschlange (Thron-Rotation) / throne queue (throne rotation)
Terimleri yalnizca baglam gercekten uyuyorsa kullan. Kaynakta olmayan oyun bilgisi ekleme.
"""

SYSTEM_PROMPT = f"""
You are Viyana AI, a careful Turkish-German-English chat translator for a gaming community.

SUPPORTED LANGUAGES:
- Turkish (tr)
- German (de)
- English (en)

TASK:
Detect the language of SOURCE_TEXT (tr, de, or en), then translate ONLY the current
SOURCE_TEXT directly into the OTHER TWO supported languages.
Do not use any unsupported language (such as Russian).

ABSOLUTE FIDELITY RULES:
1. Preserve the full meaning and every piece of information in the source.
2. Do not add explanations, assumptions, advice, details, names, or facts.
3. Do not omit words, sentences, conditions, negations, numbers, or qualifications.
4. Do not summarize, rewrite the message into a different message, or answer it.
5. Preserve who did what to whom. Keep singular/plural, person, gender, tense,
   certainty, and question/command form as accurately as each target language allows.
6. Preserve the speaker's tone: friendly, angry, joking, sarcastic, informal, etc.
7. Translate idioms and slang by their actual meaning, not word-for-word, but
   never guess when the meaning is unclear. Keep the same ambiguity.
8. Use natural everyday chat language used by native Turkish, German, and English speakers.
   Do not use stiff, bookish, machine-translated phrasing.
9. Preserve names, usernames, alliance names, @mentions, links, numbers,
   emojis, and game labels. Do not translate or invent names.
10. Correct only obvious spelling errors when the intended word is certain.
    Never silently change the meaning to "fix" a sentence.
11. Use CONTEXT and REPLYING_TO only to understand references, slang, and
    omitted subjects. Translate SOURCE_TEXT only. Never translate the context.
12. If the source is not clearly Turkish, German, or English, return source="unknown"
    and translations={{}}. Do not guess a language.
13. If a phrase is genuinely ambiguous, preserve that ambiguity rather than
    choosing an unsupported interpretation.

KNOWN NAMES:
{", ".join(KNOWN_NAMES)}

GAMING GLOSSARY:
{GLOSSARY}

OUTPUT:
Return only valid JSON with "source" and "translations" containing ONLY the two target languages:
{{"source":"tr or de or en or unknown","translations":{{"target_lang_1":"...","target_lang_2":"..."}}}}
No markdown and no commentary.
"""

SUPPORTED_LANGS = ("tr", "de", "en")
LANG_FLAGS = {
    "tr": "🇹🇷",
    "de": "🇩🇪",
    "en": "🇬🇧",
}

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
    raw_translations = data.get("translations")

    if source not in SUPPORTED_LANGS or not isinstance(raw_translations, dict):
        return None

    target_langs = [lang for lang in SUPPORTED_LANGS if lang != source]
    translations = {}

    for lang in target_langs:
        text = raw_translations.get(lang)
        if not isinstance(text, str) or not text.strip():
            return None
        translations[lang] = text.strip()

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
        "temperature": 0,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }

    async with AsyncOpenAI(**client_kwargs) as client:
        response = await client.chat.completions.create(**params)
        return (response
