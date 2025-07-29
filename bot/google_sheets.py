# bot/google_sheets.py

import os
import logging
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from bot.column_mapping import COLUMN_ORDER

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Загружаем переменные окружения
load_dotenv()
CREDS_PATH = os.getenv('GOOGLE_SHEETS_CREDS')
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')

def init_gsheets_client():
    """Инициализация и авторизация клиента Google Sheets."""
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_PATH, scope)
    client = gspread.authorize(creds)
    return client

def save_user_to_gsheets(answers: dict) -> bool:
    """
    Записывает ответы пользователя в Google Sheets в строгом порядке колонок COLUMN_ORDER.
    :param answers: dict — словарь ответов пользователя
    :return: bool — успех операции
    """
    try:
        logging.info(f"Подключение к Google Sheets: CREDS_PATH={CREDS_PATH}, SHEET_ID={SHEET_ID}")
        client = init_gsheets_client()
        sheet = client.open_by_key(SHEET_ID).sheet1
        # Строгое формирование строки данных — по порядку колонок
        row = [answers.get(key, "") for key in COLUMN_ORDER]
        sheet.append_row(row)
        logging.info(f"Данные записаны успешно: {row}")
        return True
    except Exception as e:
        logging.error(f"Ошибка записи в Google Sheets: {e}", exc_info=True)
        return False

