import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler

from config import BOT_TOKEN, API_KEY
from cache import ScheduleCache
from user_routes import UserRoutes
from handlers import BotHandlers, SELECTING_ACTION, CHOOSING_STATION_FROM, CHOOSING_STATION_TO, SAVING_ROUTE, MANAGING_ROUTES

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def main():
    
    if BOT_TOKEN == "BotAPI" or API_KEY == "YaAPI":
        print("❌ Пожалуйста, установите ваш BOT_TOKEN и API_KEY в config.py")
        return
    

    schedule_cache = ScheduleCache()
    user_routes = UserRoutes()
    bot_handlers = BotHandlers(schedule_cache, user_routes)
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot_handlers.start)],
        states={
            SELECTING_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.handle_main_menu)
            ],
            CHOOSING_STATION_FROM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.handle_station_from)
            ],
            CHOOSING_STATION_TO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.handle_station_to)
            ],
            SAVING_ROUTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.handle_save_route)
            ],
            MANAGING_ROUTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handlers.handle_manage_routes)
            ],
        },
        fallbacks=[CommandHandler('cancel', bot_handlers.cancel)],
    )
    

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("myroutes", bot_handlers.manage_routes))
    application.add_handler(CommandHandler("cache_info", bot_handlers.cache_info))
    
    logger.info("Запускаю предварительную загрузку популярных маршрутов...")
    schedule_cache.prefetch_popular_routes(API_KEY)
    
    schedule_cache.start_cache_updater()
    
    print("🤖 Бот запущен...")
    print("📊 Система кэширования активирована")
    print("⏱ Популярные маршруты будут обновляться каждые 24 часа")
    
    application.run_polling(allowed_updates=None)

if __name__ == '__main__':
    main()