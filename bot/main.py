# main.py
# Основной файл Telegram-бота для кастдев-опроса с поддержкой уточняющих вопросов и защитой от повторных ответов.

import logging
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from datetime import datetime
import os

from bot.config import BOT_TOKEN
from bot.google_sheets import save_user_to_gsheets
from bot.questions import questions

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

# --- СЛУЖЕБНЫЕ КЛЮЧИ и настройки ---
# Порядок и соответствие колонок для Google Sheets (должен совпадать с column_mapping.py)
BASIC_KEYS = [
    "gender", "age", "first_time", "visit_source", "visit_frequency", "last_visit_satisfaction",
    "last_visit_issues", "cuisine_preference", "menu_satisfaction", "avg_bill",
    "reservation_preference", "important_factors", "delivery_interest", "loyalty_program",
    "recommendation_willingness", "improvement_needed"
]
# Ключи уточняющих вопросов и их условия появления
SPECIAL_QUESTIONS = {
    "last_visit_issues": {
        "value": "🟢 Да",
        "ask_key": "issues_description"
    },
    "menu_satisfaction": {
        "value": "🍲 Не хватает определённых блюд",
        "ask_key": "menu_wishes"
    },
    "improvement_needed": {
        "value": "👍 Да",
        "ask_key": "improvement_suggestions"
    }
}

# Быстрый доступ к вопросам по ключу
QUESTIONS_BY_KEY = {q["key"]: q for q in questions}

class SurveyStates(StatesGroup):
    survey = State()

# --- Команды меню ---
@router.message(Command("help"))
async def help_command(message: Message):
    text = (
        "ℹ️ <b>Помощь по боту</b>\n\n"
        "/start — 🚀 начать опрос\n"
        "/help — ❓ помощь и инструкция\n"
        "/about — 🍽️ о проекте\n"
        "/cancel — ❌ отменить опрос\n"
        "/privacy — 🔒 политика конфиденциальности\n\n"
        "Бот задаёт вопросы о вашем опыте посещения ресторана. Ответы анонимны и нужны для улучшения сервиса!"
    )
    await message.answer(text)

@router.message(Command("about"))
async def about_command(message: Message):
    text = (
        "🍽️ <b>О проекте</b>\n\n"
        "Этот бот создан для анонимного опроса гостей ресторана. Ваши ответы помогут нам стать лучше!\n"
        "Все данные сохраняются в Google Таблицу и используются только для анализа качества обслуживания."
    )
    await message.answer(text)

@router.message(Command("privacy"))
async def privacy_command(message: Message):
    text = (
        "🔒 <b>Конфиденциальность</b>\n\n"
        "Мы не собираем ваши контактные данные. Все ответы анонимны и используются только для внутреннего анализа."
    )
    await message.answer(text)

@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Опрос отменён ❌ Если захотите пройти опрос снова — отправьте /start 🚀.")

# --- Старт опроса ---
@router.message(Command("start"))
async def start_survey(message: Message, state: FSMContext):
    # Сброс состояния и установка служебных полей
    await state.clear()
    await state.set_state(SurveyStates.survey)
    await state.update_data(
        current_q=0,
        answers={
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": message.from_user.full_name,
            "user_id": message.from_user.id
        },
        waiting_extra=None
    )
    # Приветствие
    greeting = QUESTIONS_BY_KEY.get("greeting")
    if greeting:
        await message.answer(greeting["text"])
    await ask_next_question(message, state)

# --- Основная логика: следующий вопрос ---
async def ask_next_question(message_or_call, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("current_q", 0)
    waiting_extra = data.get("waiting_extra")
    answers = data.get("answers", {})
    logging.info(f"[ask_next_question] q_index={q_index}, waiting_extra={waiting_extra}, answers={answers}")

    # Если ждём уточняющий — сначала уточняющий!
    if waiting_extra:
        extra_q = QUESTIONS_BY_KEY[waiting_extra]
        await message_or_call.answer(f"💬 {extra_q['text']}")
        await message_or_call.answer("Введите, пожалуйста, Ваш ответ:")
        return

    # Конец опроса
    if q_index >= len(BASIC_KEYS):
        await finalize_survey(message_or_call, state)
        return

    # Показать прогресс
    progress = f"Вопрос {q_index+1} из {len(BASIC_KEYS)}"
    q_key = BASIC_KEYS[q_index]
    q = QUESTIONS_BY_KEY[q_key]

    if q["type"] == "buttons":
        # Безопасный вариант для callback_data (key:index)
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=opt, callback_data=f"{q_key}:{idx}")]
                for idx, opt in enumerate(q["options"])
            ]
        )
        await message_or_call.answer(f"{progress}\n{q['text']}", reply_markup=kb)
    else:
        await message_or_call.answer(f"{progress}\n{q['text']}")
        await message_or_call.answer("Введите, пожалуйста, Ваш ответ:")

# --- Обработка кнопок (основные вопросы) ---
@router.callback_query(SurveyStates.survey)
async def process_button(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("current_q", 0)
    answers = data.get("answers", {})
    waiting_extra = data.get("waiting_extra")

    # Обработка, если ждали уточняющий (но пришла кнопка)
    if waiting_extra:
        await call.answer("Пожалуйста, ответьте текстом на уточняющий вопрос.", show_alert=True)
        return

    # Парсинг callback_data
    try:
        cb_key, idx = call.data.split(":", 1)
        idx = int(idx)
        q = QUESTIONS_BY_KEY[cb_key]
        value = q["options"][idx]
    except Exception:
        await call.answer("Ошибка: некорректный ответ.", show_alert=True)
        return

    # Защита: актуальность вопроса
    if q_index >= len(BASIC_KEYS) or BASIC_KEYS[q_index] != cb_key:
        await call.answer("Пожалуйста, отвечайте на актуальный вопрос!", show_alert=True)
        return

    # Защита от повторов
    if cb_key in answers:
        await call.answer("Вы уже ответили на этот вопрос.", show_alert=True)
        return

    answers[cb_key] = value

    # Если нужен уточняющий вопрос — спрашиваем его сразу
    if cb_key in SPECIAL_QUESTIONS and value == SPECIAL_QUESTIONS[cb_key]["value"]:
        extra_key = SPECIAL_QUESTIONS[cb_key]["ask_key"]
        if extra_key not in answers:
            await state.update_data(answers=answers, waiting_extra=extra_key)
            extra_q = QUESTIONS_BY_KEY[extra_key]
            await call.answer()
            await call.message.answer(f"💬 {extra_q['text']}")
            await call.message.answer("Введите, пожалуйста, Ваш ответ:")
            return

    # Следующий основной вопрос
    await state.update_data(answers=answers, current_q=q_index+1)
    await call.answer()
    await ask_next_question(call.message, state)

# --- Обработка текстовых ответов (основные и уточняющие вопросы) ---
@router.message(SurveyStates.survey)
async def process_text(message: Message, state: FSMContext):
    data = await state.get_data()
    q_index = data.get("current_q", 0)
    answers = data.get("answers", {})
    waiting_extra = data.get("waiting_extra")

    # Если ждём уточняющий вопрос
    if waiting_extra:
        if waiting_extra in answers:
            await message.answer("Вы уже ответили на этот вопрос.")
            return
        answers[waiting_extra] = message.text
        # Сдвигаем индекс основного вопроса на +1, чтобы не повторялся!
        await state.update_data(answers=answers, waiting_extra=None, current_q=q_index+1)
        await ask_next_question(message, state)
        return

    # Защита от “дурака”: только ожидаемый основной вопрос
    if q_index >= len(BASIC_KEYS):
        await message.answer("Опрос завершён. Спасибо!")
        return

    q_key = BASIC_KEYS[q_index]
    if q_key in answers:
        await message.answer("Вы уже ответили на этот вопрос.")
        return
    answers[q_key] = message.text
    await state.update_data(answers=answers, current_q=q_index+1)
    await ask_next_question(message, state)

# --- Финализация и запись результатов ---
async def finalize_survey(message_or_call, state: FSMContext):
    data = await state.get_data()
    answers = data.get("answers", {})
    # Запись в таблицу (Google Sheets)
    success = save_user_to_gsheets(answers)
    if success:
        await message_or_call.answer("Спасибо! Ваши ответы записаны. Приятного дня!")
    else:
        await message_or_call.answer("Произошла ошибка при сохранении данных. Попробуйте позже.")
    await state.clear()

# --- Основной запуск ---
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
