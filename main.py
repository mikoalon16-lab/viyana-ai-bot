import logging
import os
import time
import asyncio

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from openai import AsyncOpenAI
from dotenv import load_dotenv


# =========================================================
# ENV
# =========================================================

load_dotenv()


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# GPT-5.6 Luna
MODEL = "gpt-5.6-luna"

# Günlük uygulama limiti
DAILY_LIMIT_USD = 0.40

# Tek mesaj maksimum karakter
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

client = None

if OPENAI_API_KEY:
    client = AsyncOpenAI(
       
