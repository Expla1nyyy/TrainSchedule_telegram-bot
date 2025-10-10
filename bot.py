import requests
import json
from datetime import datetime, timedelta
import logging
import pickle
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import pytz


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SELECTING_ACTION, CHOOSING_STATION_FROM, CHOOSING_STATION_TO, SAVING_ROUTE, MANAGING_ROUTES = range(5)


API_KEY = "YaAPI"  # <- яндекс API ключ сюда
API_URL = "https://api.rasp.yandex.net/v3.0/search/"


ROUTES_FILE = "user_routes.pkl"

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
        self.user_routes = self.load_routes()
        self.setup_handlers()
    
    def load_routes(self):
        if os.path.exists(ROUTES_FILE):
            try:
                with open(ROUTES_FILE, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки маршрутов: {e}")
        return {}
    
    def save_routes(self):
        try:
            with open(ROUTES_FILE, 'wb') as f:
                pickle.dump(self.user_routes, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения маршрутов: {e}")
    
    def get_user_routes(self, user_id: int):
        return self.user_routes.get(user_id, [])
    
    def add_user_route(self, user_id: int, route_name: str, from_station: str, from_name: str, to_station: str, to_name: str):
        if user_id not in self.user_routes:
            self.user_routes[user_id] = []
        
        for route in self.user_routes[user_id]:
            if route['from_station'] == from_station and route['to_station'] == to_station:
                return False
        
        route_data = {
            'name': route_name,
            'from_station': from_station,
            'from_name': from_name,
            'to_station': to_station,
            'to_name': to_name,
            'created_at': datetime.now()
        }
        
        self.user_routes[user_id].append(route_data)
        self.save_routes()
        return True
    
    def delete_user_route(self, user_id: int, route_index: int):
        if user_id in self.user_routes and 0 <= route_index < len(self.user_routes[user_id]):
            del self.user_routes[user_id][route_index]
            if not self.user_routes[user_id]:
                del self.user_routes[user_id]
            self.save_routes()
            return True
        return False
    
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
                SAVING_ROUTE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_save_route)
                ],
                MANAGING_ROUTES: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_manage_routes)
                ],
            },
            fallbacks=[CommandHandler('cancel', self.cancel)],
        )
        
        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("myroutes", self.show_my_routes))
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.message.from_user
        logger.info("Пользователь %s начал разговор", user.first_name)
        
        context.user_data.pop('waiting_for_route_name', None)
        
        user_routes = self.get_user_routes(user.id)
        
        keyboard = [
            ["📅 Получить расписание"],
            ["⭐ Мои маршруты"] if user_routes else ["⭐ Добавить маршрут"],
        ]
        
        if user_routes:
            for route in user_routes[:3]:
                keyboard.append([f"🚆 {route['name']}"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот для поиска расписаний электричек с использованием Yandex.API.\n"
            "Выберите действие:",
            reply_markup=reply_markup
        )
        
        return SELECTING_ACTION
    
    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        user_id = update.message.from_user.id
        
        user_routes = self.get_user_routes(user_id)
        for i, route in enumerate(user_routes):
            if f"🚆 {route['name']}" == text:

                context.user_data['from_station'] = route['from_station']
                context.user_data['from_station_name'] = route['from_name']
                context.user_data['to_station'] = route['to_station']
                context.user_data['to_station_name'] = route['to_name']
                await self.get_schedule(update, context, is_favorite=True)
                return await self.start(update, context)
        
        if "расписание" in text.lower():
            return await self.ask_station_from(update, context)
        
        elif "мои маршруты" in text.lower() or "маршрут" in text.lower():
            return await self.manage_routes(update, context)
        
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
        
        # Сохраняем выбранную станцию отправления
        if station_name in POPULAR_STATIONS:
            context.user_data['from_station'] = POPULAR_STATIONS[station_name]
            context.user_data['from_station_name'] = station_name
        else:
            # Поиск станции по названию
            station_code, full_name = await self.search_station(station_name)
            if station_code:
                context.user_data['from_station'] = station_code
                context.user_data['from_station_name'] = full_name
            else:
                await update.message.reply_text("❌ Станция не найдена. Попробуйте еще раз:")
                return CHOOSING_STATION_FROM
        
        # Запрашиваем станцию назначения
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

        await self.show_schedule(update, context)
        
        user_routes = self.get_user_routes(update.message.from_user.id)
        if len(user_routes) < 10: 
            keyboard = [["💾 Сохранить маршрут"], ["❌ Не сохранять"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Хотите сохранить этот маршрут в избранное для быстрого доступа?",
                reply_markup=reply_markup
            )
            return SAVING_ROUTE
        else:
            await update.message.reply_text("⚠️ Достигнут лимит избранных маршрутов (10)")
            return await self.start(update, context)
    
    async def handle_save_route(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        
        if "сохранить" in text.lower():
            await update.message.reply_text(
                "Придумайте название для этого маршрута (например: 'Работа-дом'):",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data['waiting_for_route_name'] = True
            return SAVING_ROUTE
        
        elif "не сохранять" in text.lower():
            return await self.start(update, context)
        
        elif context.user_data.get('waiting_for_route_name'):
            route_name = text.strip()
            user_id = update.message.from_user.id
            
            if route_name:
                from_station = context.user_data.get('from_station')
                from_name = context.user_data.get('from_station_name')
                to_station = context.user_data.get('to_station')
                to_name = context.user_data.get('to_station_name')
                
                if self.add_user_route(user_id, route_name, from_station, from_name, to_station, to_name):
                    await update.message.reply_text(f"✅ Маршрут '{route_name}' сохранен в избранное!")
                else:
                    await update.message.reply_text("❌ Этот маршрут уже сохранен")
            else:
                await update.message.reply_text("❌ Название маршрута не может быть пустым")
            
            context.user_data.pop('waiting_for_route_name', None)
            return await self.start(update, context)
        
        else:
            return await self.start(update, context)
    
    async def show_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показ расписания (без сохранения маршрута)"""
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
                await self.show_tomorrow_schedule(update, from_station, to_station, from_name, to_name)
                return
            
            message = f"🚆 *Расписание электричек:*\n"
            message += f"📍 *{from_name}* → *{to_name}*\n"
            message += f"📅 *{datetime.now().strftime('%d.%m.%Y')}*\n\n"
            
            for segment in upcoming_trains[:8]:
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
            
            if len(upcoming_trains) > 8:
                message += f"\n... и еще {len(upcoming_trains) - 8} рейсов"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка при получении расписания: {e}")
            await update.message.reply_text("❌ Произошла ошибка при получении расписания")
    
    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE, is_favorite: bool = False):
        await self.show_schedule(update, context)
    
    async def show_tomorrow_schedule(self, update: Update, from_station: str, to_station: str, from_name: str, to_name: str):
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
    
    async def manage_routes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_id = update.message.from_user.id
        user_routes = self.get_user_routes(user_id)
        
        if not user_routes:
            keyboard = [["📅 Найти расписание"], ["↩️ В главное меню"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "У вас пока нет сохраненных маршрутов.",
                reply_markup=reply_markup
            )
            return SELECTING_ACTION
        
        # Показываем список маршрутов с кнопками удаления
        keyboard = []
        for i, route in enumerate(user_routes):
            keyboard.append([f"❌ Удалить {route['name']}"])
            keyboard.append([f"🚆 {route['name']}"])
        
        keyboard.append(["📅 Найти расписание", "↩️ В главное меню"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        routes_list = "\n".join([f"🚆 {route['name']} ({route['from_name']} → {route['to_name']})" 
                               for route in user_routes])
        
        await update.message.reply_text(
            f"⭐ Ваши сохраненные маршруты:\n\n{routes_list}\n\n"
            "Выберите маршрут для просмотра расписания или удаления:",
            reply_markup=reply_markup
        )
        
        return MANAGING_ROUTES
    
    async def handle_manage_routes(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        user_id = update.message.from_user.id
        
        if "назад" in text.lower() or "главное" in text.lower():
            return await self.start(update, context)
        
        elif "расписание" in text.lower():
            return await self.ask_station_from(update, context)
        
        elif "удалить" in text.lower():
            # Удаление маршрута
            route_name = text.replace("❌ Удалить ", "").strip()
            user_routes = self.get_user_routes(user_id)
            
            for i, route in enumerate(user_routes):
                if route['name'] == route_name:
                    self.delete_user_route(user_id, i)
                    await update.message.reply_text(f"✅ Маршрут '{route_name}' удален")
                    break
            
            return await self.manage_routes(update, context)
        
        elif text.startswith("🚆 "):
            route_name = text.replace("🚆 ", "").strip()
            user_routes = self.get_user_routes(user_id)
            for route in user_routes:
                if route['name'] == route_name:
                    context.user_data['from_station'] = route['from_station']
                    context.user_data['from_station_name'] = route['from_name']
                    context.user_data['to_station'] = route['to_station']
                    context.user_data['to_station_name'] = route['to_name']
                    await self.get_schedule(update, context, is_favorite=True)
                    break
            
            return await self.manage_routes(update, context)
        
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню:")
            return MANAGING_ROUTES
    
    async def show_my_routes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return await self.manage_routes(update, context)
    
    async def search_station(self, station_name: str) -> tuple:

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
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.message.from_user
        logger.info("Пользователь %s отменил разговор", user.first_name)
        
        context.user_data.pop('waiting_for_route_name', None)
        
        await update.message.reply_text(
            "До свидания! Если понадобится расписание - напишите /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    def run(self):
        """Запуск бота"""
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)

def main():
    BOT_TOKEN = "BotKey"
    
    global API_KEY
    API_KEY = "YaAPI"
    
    if BOT_TOKEN == "" or API_KEY == "":
        print("❌ Пожалуйста, установите ваш BOT_TOKEN и API_KEY")
        return
    
    bot = YandexScheduleBot(BOT_TOKEN)
    print("🤖 Бот запущен...")
    bot.run()

if __name__ == '__main__':
    main()