import os
import pytz
from typing import Dict

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

#ключики вставлять сюда, но сначала их нужно получить
API_KEY = os.getenv("YANDEX_API_KEY", "YaAPI")
BOT_TOKEN = os.getenv("BOT_TOKEN", "BotAPI")

API_URL = "https://api.rasp.yandex-net.ru/v3.0/search/"
ROUTES_FILE = "user_routes.pkl"
DB_FILE = "schedule_cache.db"

# здесь станции популярные чтобы не вводить названия 
POPULAR_STATIONS: Dict[str, str] = {
    "Москва (Ленинградский вокзал)": "s2006004",
    "Солнечногорск (Подсолнечная)": "s9603468",
    "Клин": "s9602944", 
    "Тверь": "s9603093",
    "Торжок": "s9603013",
}

#здесь для кэша маршруты основные, по этому списку он подтягивает их в бд
POPULAR_ROUTES = [
    {
        "from_name": "Москва (Ленинградский вокзал)",
        "from_code": "s2006004",
        "to_name": "Клин",
        "to_code": "s9602944"
    },
    {
        "from_name": "Москва (Ленинградский вокзал)",
        "from_code": "s2006004",
        "to_name": "Тверь",
        "to_code": "s9603093"
    },
    {
        "from_name": "Клин",
        "from_code": "s9602944",
        "to_name": "Москва (Ленинградский вокзал)",
        "to_code": "s2006004"
    },
    {
        "from_name": "Тверь",
        "from_code": "s9603093",
        "to_name": "Москва (Ленинградский вокзал)",
        "to_code": "s2006004"
    },
    {
        "from_name": "Тверь",
        "from_code": "s9603093",
        "to_name": "Клин",
        "to_code": "s9602944"
    },
        {
        "from_name": "Клин",
        "from_code": "s9602944",
        "to_name": "Тверь",
        "to_code": "s9603093"
    },
]