import asyncio
import config
import logging
import sqlite3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import ClientSession
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import F

logging.basicConfig(level=logging.INFO)

scheduler = AsyncIOScheduler()

bot = Bot(token=config.tg_token)
dp = Dispatcher()

connection = sqlite3.connect("database.db")
cursor = connection.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS Users (
id INTEGER,
crypto TEXT NOT NULL,
min INTEGER,
max INTEGER
)
''')

connection.commit()
connection.close()

async def get_price(symbol: str):
    async with ClientSession() as session:
        headers = {
            'X-CMC_PRO_API_KEY': f"{config.coinmarket_token}"
        }
        params = {
            'symbol': symbol,
            'convert': 'USD'
        }
        async with session.get(config.url, headers=headers, params=params) as response:
            data = await response.json()
            return data['data'][symbol]['quote']['USD']['price']

@dp.message(Command('start'))
async def start_command(message: types.Message):
    await message.answer("Привет! Я бот для отслеживания курсов криптовалют. Используйте команду /set для установки порогов или команду /get для получения прикрепленных валют\n\nДля знакомства с командами напишите /help")

@dp.message(Command('help'))
async def help_command(message: types.Message):
    await message.answer("""Все доступные команды:
/start - вернуться в главное меню бота
/help - посмотреть доступные команды
/get - посмотреть все прикрепленные валюты
/set - прикрепить валюту для отслеживания, чтобы прикрепить валюту, введите команду таким образом:
    /set НАЗВАНИЕ_ВАЛЮТЫ, МИНИМАЛЬНАЯ_ЦЕНА_В_USD, МАКСИМАЛЬНАЯ_ЦЕНА_B_USD
Пример использования:
    /set TON, 6, 8

/drop - удалить все прикрепленные валюты
""")

@dp.message(Command('get'))
async def get_command(message: types.Message):
    connection = sqlite3.connect("database.db")
    cursor = connection.cursor()

    cursor.execute("SELECT crypto, min, max FROM Users WHERE id = ?", (message.from_user.id, ))
    results = cursor.fetchall()

    connection.close()

    if results == []:
        await message.answer("У Вас не прикреплена ни одна валюта! Прикрепите валюту с помощью команды /set")
    else:
        for num in results:
            await message.answer(f"Валюта: {num[0]}\nМинимальное значение: {num[1]} USD\nМаксимальное значение: {num[2]} USD")

@dp.message(Command("drop"))
async def start_command(message: types.Message):
    markup = InlineKeyboardBuilder()

    item1 = types.InlineKeyboardButton(text="Да, продолжить", callback_data="agree")
    item2 = types.InlineKeyboardButton(text="Нет, остановить", callback_data="disagree")

    markup.add(item1, item2)

    await message.answer("ВНИМАНИЕ! При применении этой команды удалятся все отслеживаемые валюты! Продолжить выполнение?", reply_markup=markup.as_markup())

@dp.callback_query(F.data == "agree")
async def agree(callback: types.CallbackQuery):
    try:
        await callback.message.answer(f"Выполняю...")

        connection = sqlite3.connect("database.db")
        cursor = connection.cursor()

        cursor.execute("DELETE FROM Users WHERE id=?", (callback.from_user.id, ))

        connection.commit()
        connection.close()

        await callback.message.answer("Удаление выполнено успешно. Чтобы добавить новые валюты используйте команду /set")
        await callback.message.delete()
    except:
        await callback.message.answer("Произошла ошибка. Повторите еще раз")


@dp.callback_query(F.data == "disagree")
async def disagree(callback: types.CallbackQuery):
    try:
        await callback.answer("Выполнение отменено. Напишите /start для перехода в главное меню.")
        await callback.message.delete()
    except:
        await callback.message.answer("Произошла ошибка. Повторите еще раз.")

@dp.message(Command('set'))
async def set_command(message: types.Message):
    try:
        
        nothing, symbol, min_threshold, max_threshold = message.text.split()
        min_threshold = float(min_threshold)
        max_threshold = float(max_threshold)
        
        connection = sqlite3.connect("database.db")
        cursor = connection.cursor()

        cursor.execute("INSERT INTO Users (id, crypto, min, max) VALUES (?, ?, ?, ?)", (message.from_user.id, symbol, min_threshold, max_threshold))
        connection.commit()
        connection.close()

        scheduler.add_job(check_prices, 'interval', minutes=config.schedule_time, args=(message.from_user.id, ), id=symbol, replace_existing=True, max_instances=10)
        print("Задача добавлена")
        await message.answer(f"Ваши значения прикреплены. Проверьте, правильно ли внесены данные и в случае несответствия удалите данные через команду /drop\nВалюта: {symbol}\nМинимальное: {min_threshold}\nМаксимальное: {max_threshold}")
        await message.answer(f"Сейчас валюта {symbol} равна: {await get_price(symbol)} USD\n\nВалюта добавлена в планировщик, в случае повышения валюты я уведомлю Вас в этом чате!")
        
    except ValueError:
        await message.answer("Вы неправильно ввели данные. Возможно, Вы допустили ошибку в написании валюты?")

async def check_prices(chat_id: int):
    try:
        connection = sqlite3.connect("database.db")
        cursor = connection.cursor()
            
        cursor.execute("SELECT crypto, min, max FROM Users WHERE id = ?", (chat_id, ))
        results = cursor.fetchall()

        print(chat_id)

        connection.commit()
        connection.close()

        for row in results:
            symbol = row[0]
            min_threshold = row[1]
            max_threshold = row[2]

            price = await get_price(symbol)
            if price < min_threshold:
                await bot.send_message(chat_id=chat_id, text=f"Цена {symbol} упала ниже {min_threshold} USD.\n\nТекущая цена: {price}")
            if price > max_threshold:
                await bot.send_message(chat_id=chat_id, text=f"Цена {symbol} поднялась выше {max_threshold} USD.\n\nТекущая цена: {price}")
            else:
                await bot.send_message(chat_id=chat_id, text="Валюта не поднялась.")
    except Exception as e:
        logging.debug(f"Ошибка в функции {e}")

async def main():
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())