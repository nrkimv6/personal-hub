from telegram import Bot
from telegram.error import TelegramError

TOKEN = '7912548094:AAGp1Ii05IPFpM3uec75NTzJceYwrq2Lb4g'

async def get_chat_id():
    try:
        bot = Bot(token=TOKEN)
        updates = await bot.get_updates()
        for update in updates:
            if update.message:
                print(f"Chat ID: {update.message.chat_id}")
    except TelegramError as e:
        print(f"에러 발생: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(get_chat_id()) 

#7774293093