import logging
import os
import random
import re
import sqlite3
import time
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
)
from openai import OpenAI

# =========================================================
# ENVIRONMENT VARIABLES & CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

OPENAI_MODEL = "gpt-4o-mini"
DAILY_BUDGET_USD = 0.20
INPUT_PRICE_PER_MILLION = 0.15
OUTPUT_PRICE_PER_MILLION = 0.60

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================================================
# DATABASE (SQLITE)
# =========================================================

def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    # Kullanıcı Ekonomi & XP Tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            coins INTEGER DEFAULT 100,
            title TEXT DEFAULT 'Yeni Üye'
        )
    """)
    conn.commit()
    conn.close()

def add_xp_and_coins(user_id, chat_id, xp_amount=10, coin_amount=5):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT xp, level, coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, chat_id, xp, level, coins) VALUES (?, ?, ?, ?, ?)",
            (user_id, chat_id, xp_amount, 1, 100 + coin_amount)
        )
    else:
        new_xp = row[0] + xp_amount
        new_level = int(new_xp / 100) + 1  # Her 100 XP = 1 Seviye
        new_coins = row[2] + coin_amount
        
        # Unvan Ataması
        title = "Bronz Üye 🥉"
        if new_level >= 5: title = "Gümüş Üye 🥈"
        if new_level >= 10: title = "Altın Üye 🥇"
        if new_level >= 20: title = "Sohbet Kralı 👑"

        cursor.execute(
            "UPDATE users SET xp = ?, level = ?, coins = ?, title = ? WHERE user_id = ?",
            (new_xp, new_level, new_coins, title, user_id)
        )
        
    conn.commit()
    conn.close()

# =========================================================
# OPENAI CLIENT & HELPERS
# =========================================================

client = None

def get_openai_client():
    global client
    if client is None and OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
    return client

def ask_ai_short(prompt, system_role="Sen komik, zeki ve esprili bir asistansın."):
    openai_client = get_openai_client()
    if not openai_client:
        return "⚠️ OpenAI API anahtarı bulunamadı."
    
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,  # Token tasarrufu
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI Hata: {e}")
        return "⚠️ Yanıt üretilirken bir hata oluştu."

# =========================================================
# KOMUT HANDLERLARI
# =========================================================

async def profile_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT xp, level, coins, title FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        xp, level, coins, title = row
        text = (
            f"👤 **{update.effective_user.first_name} Profil Kartı**\n\n"
            f"🏅 **Unvan:** {title}\n"
            f"⭐ **Seviye:** {level}\n"
            f"✨ **XP:** {xp}\n"
            f"🪙 **Bakiye:** {coins} Coin"
        )
    else:
        text = "Henüz profiliniz oluşmadı. Mesaj atarak XP kazanmaya başlayın!"
    
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def cuzdan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    coins = row[0] if row else 0
    await update.effective_message.reply_text(f"👛 Cüzdan Bakiye: **{coins} Coin**", parse_mode="Markdown")

async def yazitura_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Kullanım: `/yazitura <miktar>`", parse_mode="Markdown")
        return
    
    bet = int(context.args[0])
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row or row[0] < bet:
        await update.effective_message.reply_text("❌ Yetersiz bakiye!")
        conn.close()
        return

    outcome = random.choice(["Yazı", "Tura"])
    user_choice = random.choice(["Yazı", "Tura"])
    
    if outcome == user_choice:
        new_coins = row[0] + bet
        msg = f"🪙 **{outcome}** geldi! Tebrikler, **{bet} Coin** kazandınız!"
    else:
        new_coins = row[0] - bet
        msg = f"🪙 **{outcome}** geldi! Maalesef **{bet} Coin** kaybettiniz."

    cursor.execute("UPDATE users SET coins = ? WHERE user_id = ?", (new_coins, user_id))
    conn.commit()
    conn.close()
    await update.effective_message.reply_text(msg, parse_mode="Markdown")

async def lakap_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.effective_message.reply_text("Lütfen lakap takmak istediğiniz kişinin mesajını yanıtlayarak `/lakap` yazın.")
        return
    
    target_user = update.message.reply_to_message.from_user.first_name
    sample_text = update.message.reply_to_message.text or "Sessizce duruyor."
    
    prompt = f"Kullanıcı: {target_user}. Mesajı: '{sample_text}'. Bu kişiye mesajına uygun komik, esprili 2-3 kelimelik bir lakap tak."
    lakap = ask_ai_short(prompt)
    
    await update.effective_message.reply_text(f"🎭 **{target_user}** için yeni lakap:\n👉 **{lakap}**", parse_mode="Markdown")

async def mahkeme_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.effective_message.reply_text("Mahkemeyi başlatmak için bir üyenin mesajını yanıtlayın!")
        return

    accuser = update.effective_user.first_name
    accused = update.message.reply_to_message.from_user.first_name
    case_text = update.message.reply_to_message.text or "Anlaşmazlık."

    prompt = f"Davacı: {accuser}, Davalı: {accused}. Olay: '{case_text}'. Sen mizahi bir hakimsin. Eğlenceli bir karar ver ve sembolik komik bir ceza kes."
    karar = ask_ai_short(prompt, system_role="Yüksek mahkeme başkanı mizahi hakim.")
    
    await update.effective_message.reply_text(f"⚖️ **VİYANA MAHKEMESİ KARARI** ⚖️\n\n{karar}", parse_mode="Markdown")

async def fal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    prompt = f"{user_name} için bugünle ilgili çok absürt, komik ve 1 cümlelik bir kehanet/fal söyle."
    fal = ask_ai_short(prompt)
    await update.effective_message.reply_text(f"🔮 **{user_name} için Günün Falı:**\n\n_{fal}_", parse_mode="Markdown")

# =========================================================
# MESAJ HANDLER
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_chat:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Ücretsiz XP & Coin Ekleme
    add_xp_and_coins(user_id, chat_id)

    # Otomatik Hoş Geldin Mesajı
    if update.message.new_chat_members:
        for new_member in update.message.new_chat_members:
            welcome_text = (
                f"🎉 **Aramıza Hoş Geldin {new_member.first_name}!**\n\n"
                f"Sohbet ederek seviye atlayabilir, `/profil` yazarak durumunu görebilirsin."
            )
            await update.effective_message.reply_text(welcome_text, parse_mode="Markdown")

# =========================================================
# MAIN
# =========================================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN bulunamadı!")

    init_db()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Komutlar
    app.add_handler(CommandHandler("profil", profile_handler))
    app.add_handler(CommandHandler("cuzdan", cuzdan_handler))
    app.add_handler(CommandHandler("yazitura", yazitura_handler))
    app.add_handler(CommandHandler("lakap", lakap_handler))
    app.add_handler(CommandHandler("mahkeme", mahkeme_handler))
    app.add_handler(CommandHandler("fal", fal_handler))

    # Mesaj dinleyici
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("🤖 Viyana AI Bot Aktif!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
