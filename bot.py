import requests
import json
from datetime import datetime, timedelta
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import pytz


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


SELECTING_ACTION, CHOOSING_STATION_FROM, CHOOSING_STATION_TO = range(3)

API_KEY = "YaAPI" #сюда ключ из яндекса
API_URL = "https://api.rasp.yandex.net/v3.0/search/"

POPULAR_STATIONS = { 
    "Москва (Ленинградский вокзал)": "s2006004",
    "Солнечногорск (Подсолнечная)": "s9603468",
    "Клин": "s9602944", 
    "Тверь": "s9603093",
    "Торжок": "s9603013",
}

class YandexScheduleBot:
    def __init__(self, token: str):
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.start)],
            states={
                SELECTING_ACTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_main_menu)
                ],
                CHOOSING_STATION_FROM: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_station_from)
                ],
                CHOOSING_STATION_TO: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_station_to)
                ],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        
        self.application.add_handler(conv_handler)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.message.from_user
        logger.info("Пользователь %s начал разговор", user.first_name)
        
        keyboard = [
            ["📅 Получить расписание"],
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот для поиска расписаний электричек с использованием Yandex.API.\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )
        
        return SELECTING_ACTION
    
    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        
        if "расписание" in text.lower():
            return await self.ask_station_from(update, context)
        
        elif "быстрый поиск" in text.lower():
            await self.quick_schedule(update, context)
            return SELECTING_ACTION
        
        
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню:")
            return SELECTING_ACTION
    
    async def ask_station_from(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        keyboard = [[station] for station in POPULAR_STATIONS.keys()]
        keyboard.append(["↩️ Назад"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Выберите станцию отправления из списка или введите название своей станции:",
            reply_markup=reply_markup
        )
        return CHOOSING_STATION_FROM
    
    async def handle_station_from(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        station_name = update.message.text
        
        if "назад" in station_name.lower():
            return await self.start(update, context)
        
        if station_name in POPULAR_STATIONS:
            context.user_data['from_station'] = POPULAR_STATIONS[station_name]
            context.user_data['from_station_name'] = station_name
        else:
            station_code, full_name = await self.search_station(station_name)
            if station_code:
                context.user_data['from_station'] = station_code
                context.user_data['from_station_name'] = full_name
            else:
                await update.message.reply_text("❌ Станция не найдена. Попробуйте еще раз:")
                return CHOOSING_STATION_FROM
        
        keyboard = [[station] for station in POPULAR_STATIONS.keys()]
        keyboard.append(["↩️ Назад"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            f"📍 Отправление: {context.user_data['from_station_name']}\n"
            "Теперь выберите станцию назначения:",
            reply_markup=reply_markup
        )
        
        return CHOOSING_STATION_TO
    
    async def handle_station_to(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
 
        station_name = update.message.text
        
        if "назад" in station_name.lower():
            return await self.ask_station_from(update, context)
        
        if station_name in POPULAR_STATIONS:
            context.user_data['to_station'] = POPULAR_STATIONS[station_name]
            context.user_data['to_station_name'] = station_name
        else:
            station_code, full_name = await self.search_station(station_name)
            if station_code:
                context.user_data['to_station'] = station_code
                context.user_data['to_station_name'] = full_name
            else:
                await update.message.reply_text("❌ Станция не найдена. Попробуйте еще раз:")
                return CHOOSING_STATION_TO
        
        await self.get_schedule(update, context)
        return await self.start(update, context)
    
    async def search_station(self, station_name: str) -> tuple:
        """Поиск кода станции по названию"""
        try:
            url = "https://api.rasp.yandex.net/v3.0/stations_list/"
            params = {
                "apikey": API_KEY,
                "format": "json",
                "lang": "ru_RU",
                "station": station_name
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()  
            data = response.json()
            
            if data.get('countries'):
                for country in data['countries']:
                    for region in country.get('regions', []):
                        for settlement in region.get('settlements', []):
                            for station in settlement.get('stations', []):
                                if station_name.lower() in station['title'].lower():
                                    return station['codes']['yandex_code'], station['title']
            
            return None, None
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка сети при поиске станции: {e}")
            return None, None
        except Exception as e:
            logger.error(f"Ошибка при поиске станции: {e}")
            return None, None
    
    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Получение расписания только предстоящих электричек"""
        try:
            from_station = context.user_data.get('from_station')
            to_station = context.user_data.get('to_station')
            from_name = context.user_data.get('from_station_name')
            to_name = context.user_data.get('to_station_name')
            
            if not from_station or not to_station:
                await update.message.reply_text("❌ Ошибка: не указаны станции")
                return
            
            params = {
                "apikey": API_KEY,
                "format": "json",
                "from": from_station,
                "to": to_station,
                "lang": "ru_RU",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "transport_types": "suburban",
                "limit": 50 
            }
            
            response = requests.get(API_URL, params=params, timeout=10)
            data = response.json()
            
            # Отладочная информация
            logger.info(f"Найдено сегментов: {len(data.get('segments', []))}")
            for i, segment in enumerate(data.get('segments', [])[:3]):
                departure_time = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                logger.info(f"Рейс {i}: {segment['departure']} -> {departure_time}")
            
            if 'segments' not in data or not data['segments']:
                await update.message.reply_text("❌ Рейсов не найдено на сегодня")
                return
            
            now_utc = datetime.now(pytz.UTC)
            
            upcoming_trains = []
            
            for segment in data['segments']:
                departure_time = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                
                if departure_time >= now_utc:
                    upcoming_trains.append(segment)

            upcoming_trains.sort(key=lambda x: x['departure'])
            
            if not upcoming_trains:

                await self.get_tomorrow_schedule(update, context, from_station, to_station, from_name, to_name)
                return
            
            message = f"🚆 *Расписание электричек (предстоящие):*\n"
            message += f"📍 *{from_name}* → *{to_name}*\n"
            message += f"📅 *{datetime.now().strftime('%d.%m.%Y')}*\n\n"
            
            for segment in upcoming_trains[:10]: 
                departure = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                arrival = datetime.strptime(segment['arrival'], '%Y-%m-%dT%H:%M:%S%z')
                
                time_until_departure = departure - now_utc
                total_minutes = int(time_until_departure.total_seconds() // 60)
                hours_until = total_minutes // 60
                minutes_until = total_minutes % 60
                
                time_until_text = ""
                if hours_until > 0:
                    time_until_text = f"⏳ Через {hours_until}ч {minutes_until}мин"
                else:
                    time_until_text = f"⏳ Через {minutes_until}мин"
                
                departure_local = departure.astimezone().strftime('%H:%M')
                arrival_local = arrival.astimezone().strftime('%H:%M')
                
                message += (
                    f"🕐 *{departure_local}* - {arrival_local}\n"
                    f"🚄 {segment['thread']['title']}\n"
                    f"⏱ В пути: {segment['duration'] // 60} мин\n"
                    f"{time_until_text}\n"
                    f"——\n"
                )
            
            if len(upcoming_trains) > 10:
                message += f"\n... и еще {len(upcoming_trains) - 10} рейсов"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка при получении расписания: {e}")
            await update.message.reply_text("❌ Произошла ошибка при получении расписания")
    
    async def get_tomorrow_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                  from_station: str, to_station: str, from_name: str, to_name: str):
        try:
            tomorrow = datetime.now() + timedelta(days=1)
            
            params = {
                "apikey": API_KEY,
                "format": "json",
                "from": from_station,
                "to": to_station,
                "lang": "ru_RU",
                "date": tomorrow.strftime("%Y-%m-%d"),
                "transport_types": "suburban",
                "limit": 5
            }
            
            response = requests.get(API_URL, params=params, timeout=10)
            data = response.json()
            
            if 'segments' not in data or not data['segments']:
                await update.message.reply_text("❌ Рейсов не найдено ни на сегодня, ни на завтра")
                return
            
            message = f"🚆 *Расписание на завтра:*\n"
            message += f"📍 *{from_name}* → *{to_name}*\n"
            message += f"📅 *{tomorrow.strftime('%d.%m.%Y')}*\n\n"
            
            for segment in data['segments'][:5]:
                departure = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                arrival = datetime.strptime(segment['arrival'], '%Y-%m-%dT%H:%M:%S%z')
                
                departure_local = departure.astimezone().strftime('%H:%M')
                arrival_local = arrival.astimezone().strftime('%H:%M')
                
                message += (
                    f"🕐 *{departure_local}* - {arrival_local}\n"
                    f"🚄 {segment['thread']['title']}\n"
                    f"⏱ В пути: {segment['duration'] // 60} мин\n"
                    f"——\n"
                )
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка при получении расписания на завтра: {e}")
            await update.message.reply_text("❌ На сегодня рейсов нет, но произошла ошибка при проверке на завтра")
    
    async def quick_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Быстрый поиск расписания (заглушка)"""
        await update.message.reply_text("🚧 Функция быстрого поиска в разработке")
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отмена разговора"""
        user = update.message.from_user
        logger.info("Пользователь %s отменил разговор", user.first_name)
        await update.message.reply_text(
            "До свидания! Если понадобится расписание - напишите /start",
            reply_markup=None
        )
        return ConversationHandler.END
    
    def run(self):
        """Запуск бота"""
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    BOT_TOKEN = "BotKey" #ключ от бота из BotFather'a
    
    global API_KEY
    API_KEY = "YaAPI" #ключ из яндекса
    
    if BOT_TOKEN == "" or API_KEY == "":
        print("❌ Пожалуйста, установите ваш BOT_TOKEN и API_KEY")
        return
    
    bot = YandexScheduleBot(BOT_TOKEN)
    print("🤖 Бот запущен...")
    bot.run()

if __name__ == '__main__':
    main()