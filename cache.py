import sqlite3
import json
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import requests

from config import API_KEY, API_URL, DB_FILE, POPULAR_ROUTES, MOSCOW_TZ

logger = logging.getLogger(__name__)

class ScheduleCache:
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
        self.cache_ttl_seconds = 86400  # 24 часа
        self.init_database()
        #бд начинается тут 
    def init_database(self):
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedule_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_station TEXT NOT NULL,
                to_station TEXT NOT NULL,
                schedule_data TEXT NOT NULL,
                last_updated TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                UNIQUE(from_station, to_station)
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_stations 
            ON schedule_cache(from_station, to_station)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_expires 
            ON schedule_cache(expires_at)
        ''')
        
        conn.commit()
        conn.close()
        
        #это вот как раз из бдшки подтягивает кэш
    def get_cached_schedule(self, from_station: str, to_station: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT schedule_data, expires_at 
            FROM schedule_cache 
            WHERE from_station = ? AND to_station = ?
        ''', (from_station, to_station))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            schedule_data, expires_at = result
            expires_datetime = datetime.fromisoformat(expires_at)
            
            if datetime.now() < expires_datetime:
                return json.loads(schedule_data)
            else:
                self.delete_cached_schedule(from_station, to_station)
                return None
        
        return None
    
    #а здесь сохраняет в бд
    def cache_schedule(self, from_station: str, to_station: str, schedule_data: Dict[str, Any]) -> None:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        now = datetime.now()
        expires_at = now + timedelta(seconds=self.cache_ttl_seconds)
        
        cursor.execute('''
            INSERT OR REPLACE INTO schedule_cache 
            (from_station, to_station, schedule_data, last_updated, expires_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            from_station, 
            to_station, 
            json.dumps(schedule_data, ensure_ascii=False), 
            now.isoformat(),
            expires_at.isoformat()
        ))
        
        conn.commit()
        conn.close()
        

    def delete_cached_schedule(self, from_station: str, to_station: str) -> None:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM schedule_cache 
            WHERE from_station = ? AND to_station = ?
        ''', (from_station, to_station))
        
        conn.commit()
        conn.close()
        
        #по истечению 24 часов жизни кэша - он удаляется
    def cleanup_expired(self) -> None:
        conn = sqlite3.connect(self.db_file)
        cursor = conn.cursor()
        
        cursor.execute('''
            DELETE FROM schedule_cache 
            WHERE expires_at < ?
        ''', (datetime.now().isoformat(),))
        
        conn.commit()
        conn.close()
        
        #здесь запросы на сохранения
    def prefetch_popular_routes(self, api_key: str) -> None:
        logger.info("Начинаю предварительную загрузку популярных маршрутов...")
        
        for route in POPULAR_ROUTES:
            try:
                schedule_data = self.fetch_schedule_from_api(
                    api_key, 
                    route["from_code"], 
                    route["to_code"]
                )
                
                if schedule_data:
                    self.cache_schedule(
                        route["from_code"], 
                        route["to_code"], 
                        schedule_data
                    )
                    logger.info(f"Загружено расписание: {route['from_name']} → {route['to_name']}")
                else:
                    logger.warning(f"Не удалось загрузить расписание: {route['from_name']} → {route['to_name']}")
                    
            except Exception as e:
                logger.error(f"Ошибка при загрузке маршрута {route['from_name']} → {route['to_name']}: {e}")
            
            time.sleep(1)  
        
        logger.info("Предварительная загрузка завершена")
    
    #здесь он из api подтягивает когда запрашивается то расписание, которого нет в кэше
    def fetch_schedule_from_api(self, api_key: str, from_station: str, to_station: str, 
                               date: str = None) -> Optional[Dict[str, Any]]:
        try:
            if not date:
                date = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
                
            params = {
                "apikey": api_key,
                "format": "json",
                "from": from_station,
                "to": to_station,
                "lang": "ru_RU",
                "date": date,
                "transport_types": "suburban",
                "limit": 50
            }
            
            response = requests.get(API_URL, params=params, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка API при получении расписания: {e}")
            return None
        except Exception as e:
            logger.error(f"Неизвестная ошибка при получении расписания: {e}")
            return None

    def start_cache_updater(self):
        def updater():
            while True:
                try:
                    self.cleanup_expired()
                    self.prefetch_popular_routes(API_KEY)
                    time.sleep(self.cache_ttl_seconds)  #запросы -> а потом отдыхать на сутки
                    
                except Exception as e:
                    logger.error(f"Ошибка в фоновом обновлении кэша: {e}")
                    time.sleep(300)  #ждем минут 5 и еще раз
        
        thread = threading.Thread(target=updater, daemon=True)
        thread.start()
        logger.info("Фоновое обновление кэша запущено")