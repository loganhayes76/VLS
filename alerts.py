import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.request import HTTPXRequest

# 1. Force the script to reload the .env file
load_dotenv()

# 2. Get the variables (Updated to match your .env names)
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

async def send_alert(message):
    # This check helps us debug in the terminal
    if not TOKEN:
        print("❌ Error: 'TELEGRAM_TOKEN' not found in .env file!")
        return
    if not CHAT_ID:
        print("❌ Error: 'TELEGRAM_CHAT_ID' not found in .env file!")
        return
    
    print(f"Connecting to Bot using Token ending in: ...{TOKEN[-5:]}")
    
    # We give it a generous 60-second window to connect
    request = HTTPXRequest(connect_timeout=60, read_timeout=60)
    bot = Bot(token=TOKEN, request=request)
    
    for attempt in range(3):
        try:
            async with bot:
                await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode='Markdown')
                print(f"📲 Success! Telegram Alert Sent on attempt {attempt + 1}.")
                return 
        except Exception as e:
            print(f"⚠️ Attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                print("⏳ Waiting 5 seconds to retry...")
                await asyncio.sleep(5)
    
    print("❌ All attempts failed. Check your internet or Bot 'Start' status.")

if __name__ == "__main__":
    asyncio.run(send_alert("🚀 Sync Test: Code and .env are now matching!"))