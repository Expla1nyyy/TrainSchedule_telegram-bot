from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from config import POPULAR_STATIONS

#здесь клавиатуры для обращений к боту

#главная
def get_main_keyboard(user_routes=None):
    keyboard = [
        ["📅 Получить расписание"],
        ["⭐ Мои маршруты"],
        ["ℹ️ Инфо о кэше"]
    ]
    
    if user_routes:
        for route in user_routes[:3]:
            keyboard.append([f"🚆 {route['name']}"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_station_selection_keyboard():
    keyboard = [[station] for station in POPULAR_STATIONS.keys()]
    keyboard.append(["↩️ Назад"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

#сохранить маршрут в избранное
def get_save_route_keyboard():
    keyboard = [
        ["💾 Сохранить маршрут"],
        ["❌ Не сохранять"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

#сохраненные маршруты
def get_manage_routes_keyboard(user_routes):
    keyboard = []
    for i, route in enumerate(user_routes):
        keyboard.append([f"❌ Удалить {route['name']}"])
        keyboard.append([f"🚆 {route['name']}"])
    
    keyboard.append(["📅 Найти расписание", "↩️ В главное меню"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup([["↩️ Назад"]], resize_keyboard=True)

def remove_keyboard():
    return ReplyKeyboardRemove()