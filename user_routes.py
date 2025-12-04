import os
import pickle
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from config import ROUTES_FILE, MOSCOW_TZ

logger = logging.getLogger(__name__)

class UserRoutes:
    def __init__(self):
        self.user_routes = self.load_routes()
    
    def load_routes(self) -> Dict[int, List[Dict[str, Any]]]:
        if os.path.exists(ROUTES_FILE):
            try:
                with open(ROUTES_FILE, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.error(f"Ошибка загрузки маршрутов: {e}")
        return {}
    
    def save_routes(self) -> None:
        try:
            with open(ROUTES_FILE, 'wb') as f:
                pickle.dump(self.user_routes, f)
        except Exception as e:
            logger.error(f"Ошибка сохранения маршрутов: {e}")
    
    def get_user_routes(self, user_id: int) -> List[Dict[str, Any]]:
        return self.user_routes.get(user_id, [])
    
    def add_user_route(self, user_id: int, route_name: str, 
                      from_station: str, from_name: str, 
                      to_station: str, to_name: str) -> bool:
        if user_id not in self.user_routes:
            self.user_routes[user_id] = []
        

        for route in self.user_routes[user_id]:
            if route['from_station'] == from_station and route['to_station'] == to_station:
                return False
        

        if len(self.user_routes[user_id]) >= 10:
            return False
        
        route_data = {
            'name': route_name,
            'from_station': from_station,
            'from_name': from_name,
            'to_station': to_station,
            'to_name': to_name,
            'created_at': datetime.now(MOSCOW_TZ)
        }
        
        self.user_routes[user_id].append(route_data)
        self.save_routes()
        return True
    
    def delete_user_route(self, user_id: int, route_index: int) -> bool:
        if user_id in self.user_routes and 0 <= route_index < len(self.user_routes[user_id]):
            del self.user_routes[user_id][route_index]
            if not self.user_routes[user_id]:
                del self.user_routes[user_id]
            self.save_routes()
            return True
        return False