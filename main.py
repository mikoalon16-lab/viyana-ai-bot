import logging
import os
import random
import sqlite3
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters
)
from openai import OpenAI

# =========================================================
# CONFIG & ENVIRONMENT VARIABLES
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-4o-mini"

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            coins INTEGER DEFAULT 100,
            title TEXT DEFAULT 'Yeni Üye',
            last_daily INTEGER DEFAULT 0
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
        new_level = int(new_xp / 100) + 1
        new_coins = row[2] + coin_amount
        
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
# AI ASSISTANT (OPENAI)
# =========================================================

client = None
def get_openai_client():
    global client
    if client is None and OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
    return client

def ask_ai_short(prompt, system_role="Sen Viyana AI asistanısın. Komik, zeki ve yardımseversin."):
    openai_client = get_openai_client()
    if not openai_client:
        return "⚠️ OpenAI API anahtarı ayarlanmamış."
    try:
        response = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_role},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI Hata: {e}")
        return "⚠️ Yanıt oluşturulurken bir hata oluştu."

# =========================================================
# KOMUT HANDLERLARI (BOTFATHER LISTESI ILE UYUMLU)
# =========================================================

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 **Merhaba! Ben Viyana AI.**\n\n"
        "Çeviri, yapay zeka sohbeti, grup içi oyunlar ve ekonomi sistemi ile hizmetinizdeyim.\n\n"
        "📌 /viana - AI Asistan ile sohbet et\n"
        "📌 /oyun - Eğlence ve oyun menüsünü aç\n"
        "📌 /seviye - Profil durumuna bak\n"
        "📌 /hakkinda - Bot bilgilerini gör"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def hakkinda_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "ℹ️ **Viyana AI Hakkında**\n\n"
        "Ben **Viyana AI** çeviri ve yapay zeka asistan botuyum.\n"
        "👑 **Ehed** tarafından tasarlandım."
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def viana_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.effective_message.reply_text("Kullanım: `/viana Naber, nasılsın?`", parse_mode="Markdown")
        return
    
    prompt = " ".join(context.args)
    response = ask_ai_short(prompt)
    await update.effective_message.reply_text(f"🤖 **Viyana AI:**\n{response}", parse_mode="Markdown")

async def seviye_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def coin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    coins = row[0] if row else 0
    await update.effective_message.reply_text(f"👛 Cüzdan Bakiye: **{coins} Coin**", parse_mode="Markdown")

async def gunluk_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = int(time.time())
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT coins, last_daily FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if row:
        coins, last_daily = row
        if now - last_daily < 86400: # 24 saat kontrolü
            kalan_saat = int((86400 - (now - last_daily)) / 3600)
            await update.effective_message.reply_text(f"⏳ Günlük ödülünü zaten aldın! **{kalan_saat} saat** sonra tekrar dene.")
            conn.close()
            return
        
        new_coins = coins + 50
        cursor.execute("UPDATE users SET coins = ?, last_daily = ? WHERE user_id = ?", (new_coins, now, user_id))
    else:
        new_coins = 150
        cursor.execute("INSERT INTO users (user_id, coins, last_daily) VALUES (?, ?, ?)", (user_id, new_coins, now))
        
    conn.commit()
    conn.close()
    await update.effective_message.reply_text("🎁 Tebrikler! **50 Günlük Coin** hesabına eklendi!", parse_mode="Markdown")

async def das_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Kullanım: `/das <miktar>`", parse_mode="Markdown")
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

async def liderlik_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, level, coins FROM users ORDER BY level DESC, coins DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    
    text = "🏆 **VIYANA AI LİDERLİK TABLOSU** 🏆\n\n"
    for idx, row in enumerate(rows, 1):
        text += f"{idx}. Kullanıcı ({row[0]}): **Seviye {row[1]}** | {row[2]} Coin\n"
    
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def oyun_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔮 Günün Falı", callback_data="game_fal")],
        [InlineKeyboardButton("🎭 Lakap Tak", callback_data="game_lakap")],
        [InlineKeyboardButton("⚖️ Mizahi Mahkeme", callback_data="game_mahkeme")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text("🎮 **Eğlence ve Oyun Menüsü:** Bir oyun seçin!", reply_markup=reply_markup)

async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "game_fal":
        prompt = f"{query.from_user.first_name} için bugünle ilgili absürt ve komik 1 cümlelik fal söyle."
        fal = ask_ai_short(prompt)
        await query.edit_message_text(f"🔮 **{query.from_user.first_name} İçin Günün Falı:**\n\n_{fal}_", parse_mode="Markdown")
    elif query.data in ["game_lakap", "game_mahkeme"]:
        await query.edit_message_text("👉 Bu oyunu oynamak için grupta bir arkadaşının mesajını yanıtlayarak komut şeklinde yazmalısın!")

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 **Kullanım Rehberi:**\n\n"
        "• `/viana <soru>`: AI Asistan yanıtlar.\n"
        "• `/das <miktar>`: Coin bahsi oynarsın.\n"
        "• `/seviye` & `/coin`: Durumunu gösterir.\n"
        "• `/oyun`: Eğlence menüsünü açar."
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")

async def panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("⚙️ **Grup Yönetim Paneli:** Şu an için tüm sistemler aktif ve çalışır durumda.")

# --- YÖNETİCİ KOMUTLARI ---
async def ban_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.effective_message.reply_text("Lütfen banlamak istediğiniz kullanıcının mesajını yanıtlayın.")
        return
    try:
        user_id = update.message.reply_to_message.from_user.id
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.effective_message.reply_text("🚫 Kullanıcı gruptan yasaklandı.")
    except Exception as e:
        await update.effective_message.reply_text("❌ Kullanıcı yasaklanamadı (Yetki eksik olabilir).")

async def sus_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text("🔇 Kullanıcı susturma işlemi için botun grupta 'Kullanıcıları Kısıtlama' yetkisi olmalıdır.")

# =========================================================
# MESAJ HANDLER
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_chat:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    # Ücretsiz XP ve Coin ekleme
    add_xp_and_coins(user_id, chat_id)

    # Otomatik Hoş Geldin
    if update.message.new_chat_members:
        for new_member in update.message.new_chat_members:
            welcome_text = (
                f"🎉 **Aramıza Hoş Geldin {new_member.first_name}!**\n\n"
                f"Sohbet ederek XP kazanabilir, `/seviye` ile durumuna bakabilirsin."
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

    # BotFather Liste Komutları
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("viana", viana_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CommandHandler("oyun", oyun_handler))
    app.add_handler(CommandHandler("hakkinda", hakkinda_handler))
    app.add_handler(CommandHandler("panel", panel_handler))
    app.add_handler(CommandHandler("coin", coin_handler))
    app.add_handler(CommandHandler("seviye", seviye_handler))
    app.add_handler(CommandHandler("gunluk", gunluk_handler))
    app.add_handler(CommandHandler("liderlik", liderlik_handler))
    app.add_handler(CommandHandler("das", das_handler))
    app.add_handler(CommandHandler("ban", ban_handler))
    app.add_handler(CommandHandler("sus", sus_handler))

    # Callback & Mesaj Dinleyiciler
    app.add_handler(CallbackQueryHandler(button_click_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    logger.info("🤖 Viyana AI Bot Başarıyla Başlatıldı!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
