import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
import requests

from config import API_KEY, API_URL, MOSCOW_TZ, POPULAR_STATIONS, DB_FILE, POPULAR_ROUTES
from keyboards import (
    get_main_keyboard, get_station_selection_keyboard, 
    get_save_route_keyboard, get_manage_routes_keyboard,
    remove_keyboard
)
from user_routes import UserRoutes
from cache import ScheduleCache

logger = logging.getLogger(__name__)

SELECTING_ACTION, CHOOSING_STATION_FROM, CHOOSING_STATION_TO, SAVING_ROUTE, MANAGING_ROUTES = range(5)

class BotHandlers:
    def __init__(self, schedule_cache: ScheduleCache, user_routes: UserRoutes):
        self.schedule_cache = schedule_cache
        self.user_routes = user_routes
    
    #эту штуку про время я добавил потому что на сервере в колледже время на 3 часа раньше и толком не настраивается
    def get_moscow_time(self):
        return datetime.now(MOSCOW_TZ)
    
    def format_moscow_time(self, dt):
        if dt.tzinfo is None:
            dt = MOSCOW_TZ.localize(dt)
        else:
            dt = dt.astimezone(MOSCOW_TZ)
        return dt
    
    # Поехали! - Юрий Гагарин (здесь хэндлер /start)
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.message.from_user
        logger.info("Пользователь %s начал разговор", user.first_name)
        
        context.user_data.clear()
        
        user_route_list = self.user_routes.get_user_routes(user.id)
        current_time = self.get_moscow_time().strftime("%H:%M")
        
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот для поиска расписаний электричек с использованием Yandex.API.\n"
            f"🕐 Текущее московское время: {current_time}\n"
            f"📊 Использую кэшированные данные для быстрого ответа\n"
            "Выберите действие:",
            reply_markup=get_main_keyboard(user_route_list)
        )
        
        return SELECTING_ACTION
    
    async def handle_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        user_id = update.message.from_user.id
        
        user_route_list = self.user_routes.get_user_routes(user_id)
        
        if "кэш" in text.lower() or "инфо" in text.lower():
            await self.cache_info(update, context)
            return SELECTING_ACTION
        
        for route in user_route_list:
            if f"🚆 {route['name']}" == text:
                context.user_data['from_station'] = route['from_station']
                context.user_data['from_station_name'] = route['from_name']
                context.user_data['to_station'] = route['to_station']
                context.user_data['to_station_name'] = route['to_name']
                await self.get_schedule(update, context, is_favorite=True)
                return await self.start(update, context)
        
        if "расписание" in text.lower():
            return await self.ask_station_from(update, context)
        
        elif "мои маршруты" in text.lower():
            return await self.manage_routes(update, context)
        
        else:
            await update.message.reply_text("Пожалуйста, выберите действие из меню:")
            return SELECTING_ACTION
    
    async def ask_station_from(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text(
            "Выберите станцию отправления из списка или введите название своей станции:",
            reply_markup=get_station_selection_keyboard()
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
        
        await update.message.reply_text(
            f"📍 Отправление: {context.user_data['from_station_name']}\n"
            "Теперь выберите станцию назначения:",
            reply_markup=get_station_selection_keyboard()
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
        
        user_route_list = self.user_routes.get_user_routes(update.message.from_user.id)
        if len(user_route_list) < 10:
            await update.message.reply_text(
                "Хотите сохранить этот маршрут в избранное для быстрого доступа?",
                reply_markup=get_save_route_keyboard()
            )
            return SAVING_ROUTE
        else:
            await update.message.reply_text("⚠️ Достигнут лимит избранных маршрутов (10)")
            return await self.start(update, context)
    
    async def handle_save_route(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text
        
        if "не сохранять" in text.lower():
            return await self.start(update, context)
        
        elif "сохранить" in text.lower():
            await update.message.reply_text(
                "Придумайте название для этого маршрута (например: 'Работа-дом'):",
                reply_markup=remove_keyboard()
            )
            context.user_data['waiting_for_route_name'] = True
            return SAVING_ROUTE
        
        elif context.user_data.get('waiting_for_route_name'):
            route_name = text.strip()
            user_id = update.message.from_user.id
            
            if route_name:
                from_station = context.user_data.get('from_station')
                from_name = context.user_data.get('from_station_name')
                to_station = context.user_data.get('to_station')
                to_name = context.user_data.get('to_station_name')
                
                if self.user_routes.add_user_route(user_id, route_name, from_station, from_name, to_station, to_name):
                    await update.message.reply_text(f"✅ Маршрут '{route_name}' сохранен в избранное!")
                else:
                    await update.message.reply_text("❌ Этот маршрут уже сохранен или достигнут лимит")
            else:
                await update.message.reply_text("❌ Название маршрута не может быть пустым")
            
            context.user_data.pop('waiting_for_route_name', None)
            return await self.start(update, context)
        
        else:
            return await self.start(update, context)
    
    async def show_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            from_station = context.user_data.get('from_station')
            to_station = context.user_data.get('to_station')
            from_name = context.user_data.get('from_station_name')
            to_name = context.user_data.get('to_station_name')
            
            if not from_station or not to_station:
                await update.message.reply_text("❌ Ошибка: не указаны станции")
                return
            
            # Проверяем кэш
            cached_data = self.schedule_cache.get_cached_schedule(from_station, to_station)
            
            if cached_data:
                logger.info(f"Используются кэшированные данные для {from_name} → {to_name}")
                data = cached_data
                cache_used = True
            else:
                logger.info(f"Запрашиваем данные из API для {from_name} → {to_name}")
                data = self.schedule_cache.fetch_schedule_from_api(API_KEY, from_station, to_station)
                
                if data:
                    self.schedule_cache.cache_schedule(from_station, to_station, data)
                    cache_used = False
                else:
                    await update.message.reply_text("❌ Не удалось получить расписание")
                    return
            
            if 'segments' not in data or not data['segments']:
                await update.message.reply_text("❌ Рейсов не найдено на сегодня")
                return
            
            now_moscow = self.get_moscow_time()
            upcoming_trains = []
            
            for segment in data['segments']:
                departure_time = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                departure_time_moscow = self.format_moscow_time(departure_time)
                
                if departure_time_moscow >= now_moscow:
                    upcoming_trains.append(segment)
            
            upcoming_trains.sort(key=lambda x: x['departure'])
            
            if not upcoming_trains:
                await self.show_tomorrow_schedule(update, from_station, to_station, from_name, to_name, cache_used)
                return
            
            cache_status = "📊 (из кэша)" if cache_used else "🌐 (из API)"
            
            message = f"🚆 *Расписание электричек:* {cache_status}\n"
            message += f"📍 *{from_name}* → *{to_name}*\n"
            message += f"📅 *{now_moscow.strftime('%d.%m.%Y')}*\n"
            message += f"🕐 *Текущее время: {now_moscow.strftime('%H:%M')}*\n\n"
            
            for segment in upcoming_trains[:12]:
                departure = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                arrival = datetime.strptime(segment['arrival'], '%Y-%m-%dT%H:%M:%S%z')
                
                departure_moscow = self.format_moscow_time(departure)
                arrival_moscow = self.format_moscow_time(arrival)
                
                time_until_departure = departure_moscow - now_moscow
                total_minutes = int(time_until_departure.total_seconds() // 60)
                hours_until = total_minutes // 60
                minutes_until = total_minutes % 60
                
                time_until_text = ""
                if hours_until > 0:
                    time_until_text = f"⏳ Через {hours_until}ч {minutes_until}мин"
                else:
                    time_until_text = f"⏳ Через {minutes_until}мин"
                
                departure_local = departure_moscow.strftime('%H:%M')
                arrival_local = arrival_moscow.strftime('%H:%M')
                
                message += (
                    f"🕐 *{departure_local}* - {arrival_local}\n"
                    f"🚄 {segment['thread']['title']}\n"
                    f"⏱ В пути: {segment['duration'] // 60} мин\n"
                    f"{time_until_text}\n"
                    f"——\n"
                )
            
            if len(upcoming_trains) > 12:
                message += f"\n... и еще {len(upcoming_trains) - 12} рейсов"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Ошибка при получении расписания: {e}")
            await update.message.reply_text("❌ Произошла ошибка при получении расписания")
    
    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE, is_favorite: bool = False):
        await self.show_schedule(update, context)
    
    async def show_tomorrow_schedule(self, update: Update, from_station: str, to_station: str, 
                                   from_name: str, to_name: str, cache_used: bool = False):
        try:
            tomorrow = self.get_moscow_time() + timedelta(days=1)
            
            # Для завтрашнего дня всегда используем API
            params = {
                "apikey": API_KEY,
                "format": "json",
                "from": from_station,
                "to": to_station,
                "lang": "ru_RU",
                "date": tomorrow.strftime("%Y-%m-%d"),
                "transport_types": "suburban",
                "limit": 12
            }
            
            response = requests.get(API_URL, params=params, timeout=10)
            data = response.json()
            
            if 'segments' not in data or not data['segments']:
                await update.message.reply_text("❌ Рейсов не найдено ни на сегодня, ни на завтра")
                return
            
            message = f"🚆 *Расписание на завтра:*\n"
            message += f"📍 *{from_name}* → *{to_name}*\n"
            message += f"📅 *{tomorrow.strftime('%d.%m.%Y')}*\n\n"
            
            for segment in data['segments'][:12]:
                departure = datetime.strptime(segment['departure'], '%Y-%m-%dT%H:%M:%S%z')
                arrival = datetime.strptime(segment['arrival'], '%Y-%m-%dT%H:%M:%S%z')
                
                departure_moscow = self.format_moscow_time(departure)
                arrival_moscow = self.format_moscow_time(arrival)
                
                departure_local = departure_moscow.strftime('%H:%M')
                arrival_local = arrival_moscow.strftime('%H:%M')
                
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
        user_route_list = self.user_routes.get_user_routes(user_id)
        
        if not user_route_list:
            await update.message.reply_text(
                "У вас пока нет сохраненных маршрутов.",
                reply_markup=get_main_keyboard([])
            )
            return SELECTING_ACTION
        
        routes_list = "\n".join([f"🚆 {route['name']} ({route['from_name']} → {route['to_name']})" 
                               for route in user_route_list])
        
        await update.message.reply_text(
            f"⭐ Ваши сохраненные маршруты:\n\n{routes_list}\n\n"
            "Выберите маршрут для просмотра расписания или удаления:",
            reply_markup=get_manage_routes_keyboard(user_route_list)
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
            route_name = text.replace("❌ Удалить ", "").strip()
            user_route_list = self.user_routes.get_user_routes(user_id)
            
            for i, route in enumerate(user_route_list):
                if route['name'] == route_name:
                    self.user_routes.delete_user_route(user_id, i)
                    await update.message.reply_text(f"✅ Маршрут '{route_name}' удален")
                    break
            
            return await self.manage_routes(update, context)
        
        elif text.startswith("🚆 "):
            route_name = text.replace("🚆 ", "").strip()
            user_route_list = self.user_routes.get_user_routes(user_id)
            
            for route in user_route_list:
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
    
    async def cache_info(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM schedule_cache")
        total_cached = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM schedule_cache WHERE expires_at > ?", 
                      (datetime.now().isoformat(),))
        valid_cached = cursor.fetchone()[0]
        
        conn.close()
        
        await update.message.reply_text(
            f"📊 *Информация о кэше расписаний:*\n"
            f"• Всего маршрутов в кэше: {total_cached}\n"
            f"• Актуальных маршрутов: {valid_cached}\n"
            f"• Популярных маршрутов отслеживается: {len(POPULAR_ROUTES)}\n"
            f"• Время жизни кэша: 24 часа\n\n"
            f"*Популярные маршруты в кэше:*\n" + 
            "\n".join([f"• {r['from_name']} → {r['to_name']}" for r in POPULAR_ROUTES]),
            parse_mode='Markdown'
        )
    
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
        except Exception as e:
            logger.error(f"Ошибка при поиске станции: {e}")
            return None, None
    
    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.message.from_user
        logger.info("Пользователь %s отменил разговор", user.first_name)
        
        context.user_data.clear()
        
        await update.message.reply_text(
            "До свидания! Если понадобится расписание - напишите /start",
            reply_markup=remove_keyboard()
        )
        return ConversationHandler.END