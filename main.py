# =========================================================
# VİYANA AI - ÇOK DİLLİ ÇEVİRİ BOTU (GÜNCELLENMİŞ VERSİYON)
# =========================================================

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
# SYSTEM PROMPT (KATI VE DOĞAL ÇEVİRİ KURALLARI)
# =========================================================

SYSTEM_PRO
