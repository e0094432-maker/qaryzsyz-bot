"""
@Qaryzsyz_qoqam_Bot — обработчики

ПОТОКИ:
  Реструктуризация → ГКБ PDF → выбор банков → причина (кнопки) → подтверждение → docx
  Отмена ИН        → ИН PDF  → (всё читает сам) → подтверждение → docx
  Отмена суда      → ИЛ PDF  → (всё читает сам) → подтверждение → docx
  Изменение нуля   → ГКБ PDF → выбор банка → подтверждение → docx
"""
import io, logging
from aiogram import Router, F, Bot
from aiogram.types import (Message, ReplyKeyboardMarkup, KeyboardButton,
                           BufferedInputFile, InlineKeyboardMarkup,
                           InlineKeyboardButton, CallbackQuery,
                           ReplyKeyboardRemove, InputMediaVideo)
from aiogram.types import FSInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from states import Form
from banks import BANKS, find_bank
from pdf_parser import extract_text, normalize_text, parse_document, format_gkb, format_in, format_il

# ── Канал для обязательной подписки ──────────────────────────
CHANNEL_ID       = "@Qaryzsyz_Qogam2026"   # username канала
CHANNEL_LINK     = "https://t.me/Qaryzsyz_Qogam2026"

# ── Видео-инструкции по получению ГКБ ───────────────────────
# file_id получены от Telegram — видео отправляются мгновенно
GKB_VIDEO_1 = "BAACAgIAAxkDAAILgGnOWLhf9txttnYla0pyLxFwstKPAAJRmgAC9SxxSockgxpoYYlYOgQ"
GKB_VIDEO_2 = "BAACAgIAAxkDAAILgWnOWLxSARc2JE5E9WN-WTmp-RaXAAJSmgAC9SxxSsehQWzWD9stOgQ"
from generator import gen_restr, gen_otmena_in, gen_otmena_suda, gen_izmenenie_nulya, REASON_TEMPLATES

router = Router()
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# ПРОВЕРКА ПОДПИСКИ
# ══════════════════════════════════════════════════════════════

def kb_subscribe():
    """Инлайн-кнопки: подписаться + проверить."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
    ])

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """Возвращает True если пользователь подписан на CHANNEL_ID."""
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception:
        return False

async def require_subscription(message: Message, bot: Bot) -> bool:
    """
    Проверяет подписку. Если не подписан — отправляет сообщение с кнопками.
    Возвращает True если подписан (можно продолжать), False если нет.
    """
    if await is_subscribed(bot, message.from_user.id):
        return True
    await message.answer(
        "⚠️ *Для использования бота необходимо подписаться на наш канал.*\n\n"
        "Канал *Qaryzsyz Qogam* — это проект партии AMANAT, который помогает\n"
        "гражданам Казахстана в решении долговых вопросов.\n\n"
        "1️⃣ Нажмите «Подписаться на канал»\n"
        "2️⃣ Затем нажмите «Проверить подписку»",
        parse_mode="Markdown",
        reply_markup=kb_subscribe()
    )
    return False

# ══════════════════════════════════════════════════════════════
# КНОПКИ
# ══════════════════════════════════════════════════════════════

HOME_RU    = "🏠 Главное меню";   HOME_KZ    = "🏠 Басты мәзір"
CANCEL_RU  = "❌ Отмена";         CANCEL_KZ  = "❌ Болдырмау"
CONFIRM_RU = "✅ Создать заявление"; CONFIRM_KZ = "✅ Өтініш жасау"

HOME_BUTTONS    = [HOME_RU, HOME_KZ]
CANCEL_BUTTONS  = [CANCEL_RU, CANCEL_KZ]
CONFIRM_BUTTONS = [CONFIRM_RU, CONFIRM_KZ]
ALL_BACK        = HOME_BUTTONS + CANCEL_BUTTONS

BTN = {
    "restr":        ("∞ Реструктуризация",           "∞ Қайта құрылымдау"),
    "cancel_in":    ("📝 Отмена ИН",                 "📝 ИН тоқтату"),
    "cancel_court": ("⚖️ Отмена решения суда",       "⚖️ Сот шешімін тоқтату"),
    "zero_change":  ("0️⃣ Изменение нуля",             "0️⃣ Нөлді өзгерту"),
    "bankruptcy_out": ("🏳️ Внесудебное банкротство", "🏳️ Соттан тыс банкроттық"),
    "bankruptcy_court": ("⚖️ Судебное банкротство",  "⚖️ Сот арқылы банкроттық"),
}
ALL_MENU_RU = [v[0] for v in BTN.values()]
ALL_MENU_KZ = [v[1] for v in BTN.values()]
ALL_MENU    = ALL_MENU_RU + ALL_MENU_KZ
MENU_MAP    = {v[i]: k for k, v in BTN.items() for i in (0, 1)}

DOC_NAMES = {
    "restr":            "Реструктуризация долга",
    "cancel_in":        "Отмена исполнительной надписи",
    "cancel_court":     "Отмена решения суда",
    "zero_change":      "Исправление данных в ГКБ",
    "bankruptcy_out":   "Внесудебное банкротство",
    "bankruptcy_court": "Судебное банкротство",
}

REASON_BTNS = list(REASON_TEMPLATES.keys())  # последний — "✏️ Своя причина"

def gl(d): return d.get("lang", "ru")

# ──────────────────────────────────────────────────────────────
# Клавиатуры
# ──────────────────────────────────────────────────────────────

def kb_lang():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🇷🇺 Русский")],
        [KeyboardButton(text="🇰🇿 Қазақша")],
    ], resize_keyboard=True)

def kb_menu(lang):
    rows = ALL_MENU_RU if lang == "ru" else ALL_MENU_KZ
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=r)] for r in rows], resize_keyboard=True)

def kb_back(lang):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=CANCEL_RU if lang=="ru" else CANCEL_KZ)],
        [KeyboardButton(text=HOME_RU   if lang=="ru" else HOME_KZ)],
    ], resize_keyboard=True)

def kb_confirm(lang):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=CONFIRM_RU if lang=="ru" else CONFIRM_KZ)],
        [KeyboardButton(text=CANCEL_RU  if lang=="ru" else CANCEL_KZ)],
        [KeyboardButton(text=HOME_RU    if lang=="ru" else HOME_KZ)],
    ], resize_keyboard=True)

REASON_BTNS_KZ = [
    "😔 Жұмыстан шығу / қысқарту",
    "📉 Табыстың төмендеуі",
    "🏥 Ауру / емдеу",
    "👶 Декрет / балаға күтім",
    "💔 Асыраушыны жоғалту / ажырасу",
    "✏️ Өз себебім",
]

# Маппинг казахских кнопок → русские ключи REASON_TEMPLATES
REASON_KZ_TO_RU = {
    "😔 Жұмыстан шығу / қысқарту":    "😔 Потеря работы / сокращение",
    "📉 Табыстың төмендеуі":           "📉 Снижение дохода",
    "🏥 Ауру / емдеу":                 "🏥 Болезнь / лечение",
    "👶 Декрет / балаға күтім":        "👶 Декрет / уход за ребёнком",
    "💔 Асыраушыны жоғалту / ажырасу": "💔 Потеря кормильца / развод",
    "✏️ Өз себебім":                   "✏️ Своя причина",
}

def kb_reason(lang):
    btns = REASON_BTNS_KZ if lang == "kz" else REASON_BTNS
    rows = [[KeyboardButton(text=r)] for r in btns]
    rows.append([KeyboardButton(text=CANCEL_RU if lang=="ru" else CANCEL_KZ)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def is_active_credit(cr: dict) -> bool:
    """Активный кредит — просрочка > 0 или дней просрочки > 0."""
    try:
        overdue = int(str(cr.get("overdue_amount") or 0).replace(",","").replace(" ",""))
        days    = int(str(cr.get("overdue_days")    or 0))
        return overdue > 0 or days > 0
    except Exception:
        return False

def kb_gkb(credits: list, lang: str):
    # Показываем ВСЕ кредиты из ГКБ (не только активные)
    rows = []
    seen = set()
    for cr in credits:
        bank_name = cr['bank'][:38]
        if bank_name not in seen:
            seen.add(bank_name)
            rows.append([KeyboardButton(text=f"🏦 {bank_name}")])
    rows.append([KeyboardButton(text="✅ Все банки" if lang=="ru" else "✅ Барлық банктер")])
    rows.append([KeyboardButton(text=HOME_RU if lang=="ru" else HOME_KZ)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

# ══════════════════════════════════════════════════════════════
# /start → язык → меню
# ══════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    if not await is_subscribed(message.bot, message.from_user.id):
        await message.answer(
            "👋 *Салем! Здравствуйте!*\n\n"
            "Я — бот проекта *Qaryzsyz Qogam* партии *AMANAT*.\n\n"
            "Помогаю гражданам Казахстана формировать юридические заявления:\n\n"
            "∞ *Реструктуризация* — если трудно платить кредит\n"
            "📝 *Отмена ИН* — отмена исполнительной надписи нотариуса\n"
            "⚖️ *Отмена решения суда* — возражение на судебный приказ\n"
            "0️⃣ *Исправление данных ГКБ* — ошибки в кредитной истории\n\n"
            "⚠️ *Важно:* бот носит *информационный характер* и не даёт гарантий результата.\n\n"
            "📢 Для начала подпишитесь на наш канал:",
            parse_mode="Markdown",
            reply_markup=kb_subscribe()
        )
        return

    await state.set_state(Form.lang)
    await message.answer(
        "👋 *Салем! Здравствуйте!*\n\n"
        "Я — бот проекта *Qaryzsyz Qogam* партии *AMANAT*.\n\n"
        "Помогаю формировать юридические заявления:\n"
        "∞ Реструктуризация · 📝 Отмена ИН · ⚖️ Отмена суда · 0️⃣ Исправление ГКБ\n\n"
        "⚠️ Бот носит *информационный характер* и не даёт гарантий результата.\n\n"
        "🌐 Выберите язык / Тілді таңдаңыз:",
        parse_mode="Markdown",
        reply_markup=kb_lang()
    )


@router.callback_query(F.data == "check_sub")
async def check_subscription_callback(callback: CallbackQuery, state: FSMContext):
    if not await is_subscribed(callback.bot, callback.from_user.id):
        await callback.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        return
    await callback.answer("✅ Подписка подтверждена!", show_alert=False)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await state.set_state(Form.lang)
    await callback.message.answer(
        "✅ *Подписка подтверждена! Добро пожаловать.*\n\n"
        "🌐 Выберите язык / Тілді таңдаңыз:",
        parse_mode="Markdown",
        reply_markup=kb_lang()
    )

@router.message(Form.lang, F.text.in_(["🇷🇺 Русский", "🇰🇿 Қазақша"]))
async def set_lang(message: Message, state: FSMContext):
    if not await require_subscription(message, message.bot):
        return
    lang = "ru" if "Русский" in message.text else "kz"
    await state.update_data(lang=lang)
    await state.set_state(Form.menu)
    await message.answer(
        "📋 Выберите тип заявления:" if lang=="ru" else "📋 Өтініш түрін таңдаңыз:",
        reply_markup=kb_menu(lang)
    )


@router.message(F.video)
async def receive_video(message: Message):
    """
    Вспомогательный хендлер: если вы отправите видео боту —
    он ответит file_id, который нужно вставить в GKB_VIDEO_FILE_ID.
    Используется только для первоначальной настройки.
    """
    fid = message.video.file_id
    await message.answer(
        f"📋 *file_id видео:*\n`{fid}`\n\n"
        "Вставьте это значение в `GKB_VIDEO_FILE_ID` в handlers.py",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
# Возврат в меню из любого места
# ══════════════════════════════════════════════════════════════

@router.message(F.text.in_(ALL_BACK))
async def go_home(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = gl(data)
    await state.clear()
    await state.update_data(lang=lang)
    await state.set_state(Form.menu)
    await message.answer(
        "🏠 Главное меню:" if lang=="ru" else "🏠 Басты мәзір:",
        reply_markup=kb_menu(lang)
    )

# ══════════════════════════════════════════════════════════════
# МЕНЮ — выбор услуги → инструкция по загрузке PDF
# ══════════════════════════════════════════════════════════════

UPLOAD_TEXTS = {
    "restr": (
        "📋 Выберите способ:\n\n"
        "📎 *Загрузите ГКБ-отчёт* (PDF) — бот сам прочитает все банки, кредиты и суммы.\n\n"
        "✏️ Или напишите `нет` — введёте данные банка и сумму вручную.",
        "📋 Тәсілді таңдаңыз:\n\n"
        "📎 *МКБ есебін* жүктеңіз (PDF) — бот барлық деректерді оқиды.\n\n"
        "✏️ Немесе `жоқ` жазыңыз — деректерді қолмен енгізіңіз."
    ),
    "cancel_in": (
        "📎 Загрузите *исполнительную надпись* нотариуса (PDF).\n\n"
        "Бот прочитает: нотариуса, кредитора, сумму, договор — "
        "и сразу составит *возражение* по ст. 92-6, 92-8 Закона «О нотариате».",
        "📎 Нотариустың *атқару жазбасын* жүктеңіз (PDF)."
    ),
    "cancel_court": (
        "📎 Загрузите *исполнительный лист* суда (PDF).\n\n"
        "Бот прочитает: суд, дело, стороны, суммы — "
        "и составит *ходатайство об отмене решения* по ст. 126, 148 ГПК РК.",
        "📎 Соттың *атқару парағын* жүктеңіз (PDF)."
    ),
    "zero_change": (
        "📎 Загрузите *ГКБ-отчёт* (PDF).\n\n"
        "Бот найдёт банки с обнулёнными данными и составит заявление "
        "об *исправлении кредитной истории* по ст. 7, 8 Закона «О кредитных бюро».",
        "📎 *МКБ есебін* жүктеңіз (PDF)."
    ),
}

@router.message(F.text.in_(ALL_MENU))
async def menu_choice(message: Message, state: FSMContext):
    if not await require_subscription(message, message.bot):
        return
    data     = await state.get_data()
    lang     = gl(data)
    doc_type = MENU_MAP[message.text]

    # ── Банкротство — показываем подменю ─────────────────────
    if doc_type in ("bankruptcy_out", "bankruptcy_court"):
        await state.update_data(doc_type=doc_type)
        await state.set_state(Form.bankruptcy_sub)
        if doc_type == "bankruptcy_out":
            title = "🏳️ *Внесудебное банкротство*" if lang=="ru" else "🏳️ *Соттан тыс банкроттық*"
        else:
            title = "⚖️ *Судебное банкротство*" if lang=="ru" else "⚖️ *Сот арқылы банкроттық*"
        btn1 = "📋 Критерии" if lang=="ru" else "📋 Критерийлер"
        btn2 = "📖 Инструкция" if lang=="ru" else "📖 Нұсқаулық"
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text=btn1)],
            [KeyboardButton(text=btn2)],
            [KeyboardButton(text=HOME_RU if lang=="ru" else HOME_KZ)],
        ], resize_keyboard=True)
        await message.answer(title, parse_mode="Markdown", reply_markup=kb)
        return

    await state.update_data(doc_type=doc_type, parsed={}, banks_list=[])
    await state.set_state(Form.upload_file)
    ru, kz = UPLOAD_TEXTS[doc_type]

    # Для услуг требующих ГКБ — отправляем текст + 2 видео-инструкции
    gkb_services = ("restr", "zero_change")
    if doc_type in gkb_services:
        await message.answer(ru if lang=="ru" else kz, parse_mode="Markdown", reply_markup=kb_back(lang))

        cap1 = "🎥 *Видео 1: Как получить МКБ-отчёт (часть 1)*" if lang=="ru" else "🎥 *Бейне 1: МКБ есебін қалай алуға болады (1-бөлім)*"
        cap2 = "🎥 *Видео 2: Как получить МКБ-отчёт (часть 2)*" if lang=="ru" else "🎥 *Бейне 2: МКБ есебін қалай алуға болады (2-бөлім)*"

        import os
        # Ищем видео в нескольких возможных местах
        def find_video(names):
            search_dirs = [
                os.path.dirname(os.path.abspath(__file__)),
                r"C:\Users\user\Downloads\bot_v24_code",
                r"C:\Users\user\Downloads\bot_v25",
                r"C:\Users\user\Downloads",
            ]
            for d in search_dirs:
                for name in names:
                    p = os.path.join(d, name)
                    if os.path.exists(p):
                        return p
            return None

        async def send_video(names, vid_id_var, caption, var_name):
            global GKB_VIDEO_1, GKB_VIDEO_2
            vid_id = GKB_VIDEO_1 if var_name == "GKB_VIDEO_1" else GKB_VIDEO_2
            try:
                if vid_id:
                    # Уже есть file_id — отправляем мгновенно
                    await message.answer_video(video=vid_id, caption=caption, parse_mode="Markdown")
                    return
                path = find_video(names)
                if path:
                    sent = await message.answer_video(video=FSInputFile(path), caption=caption, parse_mode="Markdown")
                    # Кэшируем file_id чтобы следующие отправки были мгновенными
                    if sent and sent.video:
                        if var_name == "GKB_VIDEO_1":
                            GKB_VIDEO_1 = sent.video.file_id
                        else:
                            GKB_VIDEO_2 = sent.video.file_id
                        logger.info(f"Video {var_name} cached: {sent.video.file_id}")
                else:
                    logger.warning(f"Video not found: {names}")
            except Exception as e:
                logger.error(f"Video send error: {e}")

        await send_video(["IMG_5769.mp4", "gkb_video_1.mp4"], GKB_VIDEO_1, cap1, "GKB_VIDEO_1")
        await send_video(["IMG_5770.mp4", "gkb_video_2.mp4"], GKB_VIDEO_2, cap2, "GKB_VIDEO_2")
    else:
        await message.answer(ru if lang=="ru" else kz, parse_mode="Markdown", reply_markup=kb_back(lang))


# ══════════════════════════════════════════════════════════════
# БАНКРОТСТВО — ПОДМЕНЮ (Критерии / Инструкция)
# ══════════════════════════════════════════════════════════════

BANKRUPTCY_OUT_CRITERIA_RU = """📋 *Критерии внесудебного банкротства*

✅ *Условия для подачи:*
• Общая сумма долга — *не более 1 600 МРП* (в 2025 г. — до 6 291 200 тг)
• Просрочка более *365 дней по всем кредитам* без каких-либо платежей
• Нет открытого ИП
• Нет имущества для погашения долга

⛔ *Нельзя подать если:*
• Долг превышает 1 600 МРП — нужно судебное банкротство
• Есть хотя бы один кредит без просрочки 365+ дней
• Были платежи за последний год"""

BANKRUPTCY_OUT_CRITERIA_KZ = """📋 *Соттан тыс банкроттық критерийлері*

✅ *Өтініш беру шарттары:*
• Жалпы берешек сомасы — *1 600 АЕК-тен аспауы* (2025 ж. — 6 291 200 теңгеге дейін)
• Барлық кредиттер бойынша *365 күннен астам* мерзімі өткен берешек, ешқандай төлемсіз
• Ашық ЖК болмауы
• Берешекті өтеуге мүлік болмауы

⛔ *Өтініш беруге болмайды:*
• Берешек 1 600 АЕК-тен асса — сот арқылы банкроттық қажет
• 365+ күн мерзімі өтпеген кредит болса
• Соңғы жылда төлемдер болған болса"""

BANKRUPTCY_OUT_INSTRUCTION_RU = """📖 *Инструкция: Внесудебное банкротство*

*Шаг 1.* Получите кредитный отчёт
→ Сайт: mkb.kz → Личный кабинет → ЭЦП или QR-код
→ Раздел: «Персональный отчёт (Банкротство граждан РК)»

*Шаг 2.* Проверьте данные
→ Просрочка по всем кредитам > 365 дней
→ Нет платежей за последний год
→ Сумма долга не превышает 1 600 МРП

*Шаг 3.* Получите ЭЦП (если нет)
→ egov.kz или ЦОН

*Шаг 4.* Подайте заявление
→ Сайт: egov.kz → Услуга: «Применение процедуры внесудебного банкротства»
→ Заполните форму, загрузите отчёт ГКБ, подпишите ЭЦП

*Шаг 5.* Ожидайте ответ
→ Срок рассмотрения: *до 15 рабочих дней*
→ Статус — в личном кабинете eGov

⚠️ _Если состоите в браке — нужно подтверждение супруга/супруги через ЭЦП на eGov_"""

BANKRUPTCY_OUT_INSTRUCTION_KZ = """📖 *Нұсқаулық: Соттан тыс банкроттық*

*1-қадам.* Кредиттік есеп алыңыз
→ Сайт: mkb.kz → Жеке кабинет → ЭЦҚ немесе QR-код
→ Бөлім: «Жеке есеп (ҚР азаматтарының банкроттығы)»

*2-қадам.* Деректерді тексеріңіз
→ Барлық кредиттер бойынша мерзімі өткен берешек > 365 күн
→ Соңғы жылда ешқандай төлем болмаған
→ Берешек сомасы 1 600 АЕК-тен аспауы

*3-қадам.* ЭЦҚ алыңыз (болмаса)
→ egov.kz немесе ХҚКО

*4-қадам.* Өтініш беріңіз
→ Сайт: egov.kz → Қызмет: «Соттан тыс банкроттық рәсімін қолдану»
→ Нысанды толтырыңыз, МҚБ есебін жүктеңіз, ЭЦҚ-мен қол қойыңыз

*5-қадам.* Жауапты күтіңіз
→ Қарау мерзімі: *15 жұмыс күніне дейін*
→ Мәртебе — eGov жеке кабинетінде

⚠️ _Некеде болсаңыз — жұбайыңыздың eGov арқылы ЭЦҚ растауы қажет_"""

BANKRUPTCY_COURT_CRITERIA_RU = """📋 *Критерии судебного банкротства*

✅ *Условия для подачи:*
• Общая сумма долга — *более 1 600 МРП* (в 2025 г. — свыше 6 291 200 тг)
• Просрочка более *365 дней по всем кредитам*
• Отсутствие платежей более 1 года
• Нет открытого ИП

💰 *Расходы:*
• Госпошлина: *1 966 тг за каждого кредитора* (0,5 МРП)
• Финансовый управляющий: *85 000 тг/мес.* × 6 месяцев = 510 000 тг

⛔ *Нельзя подать если:*
• Долг менее 1 600 МРП — подходит внесудебное
• Есть кредит без просрочки 365+ дней
• Были платежи за последний год"""

BANKRUPTCY_COURT_CRITERIA_KZ = """📋 *Сот арқылы банкроттық критерийлері*

✅ *Өтініш беру шарттары:*
• Жалпы берешек сомасы — *1 600 АЕК-тен жоғары* (2025 ж. — 6 291 200 теңгеден астам)
• Барлық кредиттер бойынша *365 күннен астам* мерзімі өткен берешек
• 1 жылдан астам төлем болмауы
• Ашық ЖК болмауы

💰 *Шығындар:*
• Мемлекеттік баж: *әр кредитор үшін 1 966 теңге* (0,5 АЕК)
• Қаржы басқарушысы: *85 000 теңге/ай* × 6 ай = 510 000 теңге

⛔ *Өтініш беруге болмайды:*
• Берешек 1 600 АЕК-тен аз болса — соттан тыс банкроттық қолайлы
• 365+ күн мерзімі өтпеген кредит болса
• Соңғы жылда төлемдер болған болса"""

BANKRUPTCY_COURT_INSTRUCTION_RU = """📖 *Инструкция: Судебное банкротство*

*Шаг 1.* Получите кредитный отчёт ГКБ
→ mkb.kz → ЭЦП → «Персональный отчёт (Банкротство граждан РК)»

*Шаг 2.* Попробуйте реструктуризацию (обязательный этап!)
→ Направьте заявление о реструктуризации в каждый банк/МФО
→ Получите письменный отказ от каждого кредитора

*Шаг 3.* Соберите документы
→ Справка об отсутствии ИП (налоговый орган / E-Otinish)
→ Справка о семейном положении (ЦОН или E-Otinish)
→ Справка о доходах (eGov — ГЦВП или справка с работы)
→ Справка о составе семьи, документы на детей
→ Сведения об автомобилях за 3 года (Департамент полиции / E-Otinish)

*Шаг 4.* Оплатите госпошлину
→ Сайт: office.sud.kz → Подача документов
→ КБК 108126 → *1 966 тг × кол-во кредиторов*
→ Сохраните квитанцию об оплате

*Шаг 5.* Подайте иск в суд
→ office.sud.kz → Гражданское дело → Первая инстанция → Иск
→ Вид: Особое производство (Подраздел 4 ГПК РК)
→ Категория: Прочие дела особого производства
→ Выберите суд по месту прописки
→ Загрузите все документы и подпишите ЭЦП

*Шаг 6.* Ожидайте назначения управляющего
→ Суд назначит финансового управляющего
→ Выплата: *85 000 тг/мес.* в течение 6 месяцев"""

BANKRUPTCY_COURT_INSTRUCTION_KZ = """📖 *Нұсқаулық: Сот арқылы банкроттық*

*1-қадам.* МҚБ кредиттік есебін алыңыз
→ mkb.kz → ЭЦҚ → «Жеке есеп (ҚР азаматтарының банкроттығы)»

*2-қадам.* Қайта құрылымдауға әрекет жасаңыз (міндетті кезең!)
→ Әрбір банк/МҚҰ-ға қайта құрылымдау туралы өтініш жіберіңіз
→ Әрбір кредитордан жазбаша бас тарту алыңыз

*3-қадам.* Құжаттарды жинаңыз
→ ЖК тіркелмегені туралы анықтама (салық органы / E-Otinish)
→ Отбасылық жағдай туралы анықтама (ХҚКО немесе E-Otinish)
→ Табыс туралы анықтама (eGov — ГЦВП немесе жұмыс орнынан)
→ Отбасы құрамы туралы анықтама, балаларға құжаттар
→ 3 жылдағы автомобиль туралы мәліметтер (Полиция департаменті / E-Otinish)

*4-қадам.* Мемлекеттік баж төлеңіз
→ Сайт: office.sud.kz → Құжаттарды жіберу
→ КБК 108126 → *1 966 теңге × кредиторлар саны*
→ Төлем туралы чекті сақтаңыз

*5-қадам.* Сотқа талап арыз беріңіз
→ office.sud.kz → Азаматтық іс → Бірінші саты → Талап арыз
→ Іс жүргізу түрі: Ерекше іс жүргізу (ҚР АЖК 4-кіші бөлімі)
→ Іс санаты: Ерекше іс жүргізудің басқа да істері
→ Тіркелген мекенжайыңыз бойынша сотты таңдаңыз
→ Барлық құжаттарды жүктеп, ЭЦҚ-мен қол қойыңыз

*6-қадам.* Басқарушы тағайындалуын күтіңіз
→ Сот қаржы басқарушысын тағайындайды
→ Төлем: *85 000 теңге/ай* 6 ай бойы"""


@router.message(Form.bankruptcy_sub)
async def bankruptcy_sub_choice(message: Message, state: FSMContext):
    data     = await state.get_data()
    lang     = gl(data)
    doc_type = data.get("doc_type", "bankruptcy_out")
    text     = (message.text or "").strip()

    # Возврат в меню
    if text in ALL_BACK:
        await go_home(message, state)
        return

    is_criteria    = text in ("📋 Критерии", "📋 Критерийлер")
    is_instruction = text in ("📖 Инструкция", "📖 Нұсқаулық")

    if not is_criteria and not is_instruction:
        await message.answer("👇 Выберите раздел:" if lang=="ru" else "👇 Бөлімді таңдаңыз:")
        return

    if doc_type == "bankruptcy_out":
        if is_criteria:
            txt = BANKRUPTCY_OUT_CRITERIA_RU if lang=="ru" else BANKRUPTCY_OUT_CRITERIA_KZ
        else:
            txt = BANKRUPTCY_OUT_INSTRUCTION_RU if lang=="ru" else BANKRUPTCY_OUT_INSTRUCTION_KZ
    else:
        if is_criteria:
            txt = BANKRUPTCY_COURT_CRITERIA_RU if lang=="ru" else BANKRUPTCY_COURT_CRITERIA_KZ
        else:
            txt = BANKRUPTCY_COURT_INSTRUCTION_RU if lang=="ru" else BANKRUPTCY_COURT_INSTRUCTION_KZ

    # Разбиваем длинный текст на части
    MAX_LEN = 3800
    parts = []
    current = ""
    for line in txt.split("\n"):
        if len(current) + len(line) + 1 > MAX_LEN:
            parts.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        parts.append(current)

    for part in parts:
        await message.answer(part.strip(), parse_mode="Markdown")

    # Показываем снова подменю
    if doc_type == "bankruptcy_out":
        title = "🏳️ *Внесудебное банкротство*" if lang=="ru" else "🏳️ *Соттан тыс банкроттық*"
    else:
        title = "⚖️ *Судебное банкротство*" if lang=="ru" else "⚖️ *Сот арқылы банкроттық*"
    btn1 = "📋 Критерии" if lang=="ru" else "📋 Критерийлер"
    btn2 = "📖 Инструкция" if lang=="ru" else "📖 Нұсқаулық"
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=btn1)],
        [KeyboardButton(text=btn2)],
        [KeyboardButton(text=HOME_RU if lang=="ru" else HOME_KZ)],
    ], resize_keyboard=True)
    await message.answer(title, parse_mode="Markdown", reply_markup=kb)



# ══════════════════════════════════════════════════════════════
# ЗАГРУЗКА PDF
# ══════════════════════════════════════════════════════════════

@router.message(Form.upload_file, F.document)
async def process_file(message: Message, state: FSMContext):
    data     = await state.get_data()
    lang     = gl(data)
    doc_type = data.get("doc_type", "restr")

    try:
        f   = await message.bot.get_file(message.document.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(f.file_path, buf)
        raw = buf.getvalue()
    except Exception as e:
        logger.error(f"Download: {e}")
        await message.answer("⚠️ Не удалось скачать файл. Попробуйте ещё раз." if lang=="ru" else "⚠️ Файлды жүктеу мүмкін болмады.")
        return

    await message.answer("⏳ Читаю документ..." if lang=="ru" else "⏳ Оқып жатырмын...")

    raw_text = extract_text(raw)
    text     = normalize_text(raw_text)   # склеиваем разбитые по строкам слова
    parsed   = parse_document(text)
    ptype  = parsed.get("doc_type", "unknown")
    await state.update_data(parsed=parsed)

    # ── ОТМЕНА ИН ────────────────────────────────────────────
    if doc_type == "cancel_in":
        if ptype != "in":
            await message.answer(
                "⚠️ Файл не распознан как исполнительная надпись.\n"
                "Проверьте файл и загрузите снова, или нажмите 🏠 Главное меню."
                if lang=="ru" else
                "⚠️ Файл атқару жазбасы ретінде танылмады.\nДұрыс файл жүктеңіз."
            )
            return
        summary = format_in(parsed)
        await message.answer(summary + "\n\n✅ Данные прочитаны — создаю заявление...", parse_mode="Markdown")
        # Для ИН никаких вопросов — сразу подтверждение
        await _show_confirm(message, state, data, lang, parsed)
        return

    # ── ОТМЕНА РЕШЕНИЯ СУДА ──────────────────────────────────
    if doc_type == "cancel_court":
        if ptype != "il":
            await message.answer(
                "⚠️ Файл не распознан как исполнительный лист суда.\n"
                "Проверьте файл и загрузите снова, или нажмите 🏠 Главное меню."
                if lang=="ru" else
                "⚠️ Файл атқару парағы ретінде танылмады.\nДұрыс файл жүктеңіз."
            )
            return
        summary = format_il(parsed)
        await message.answer(summary + "\n\n✅ Данные прочитаны — создаю заявление...", parse_mode="Markdown")
        # Для ИЛ никаких вопросов — сразу подтверждение
        await _show_confirm(message, state, data, lang, parsed)
        return

    # ── ГКБ (реструктуризация / изменение нуля) ─────────────
    # Пробуем сначала нормализованный текст, затем сырой (для казахского ГКБ)
    if ptype != "gkb":
        parsed_raw = parse_document(raw_text)
        if parsed_raw.get("doc_type") == "gkb":
            parsed = parsed_raw
            ptype  = "gkb"
            await state.update_data(parsed=parsed)

    if ptype == "gkb":
        all_credits = parsed.get("credits", [])
        credits = all_credits if all_credits else []
        # Сохраняем все активные в parsed
        parsed["credits"] = credits
        await state.update_data(parsed=parsed)

        name    = parsed.get("full_name", "—")
        iin     = parsed.get("iin", "—")
        phone   = parsed.get("phone", "")
        n_cr    = len(credits)
        n_banks = len({cr["bank"] for cr in credits})

        if lang == "kz":
            header = (
                f"✅ *МКБ есебі оқылды!*\n\n"
                f"👤 ТАӘ: *{name}*\n"
                f"🪪 ЖСН: *{iin}*"
                + (f"\n📞 Тел.: *{phone}*" if phone else "")
                + f"\n\n📊 Белсенді несиелер: *{n_cr}*  |  Банктер/МҚҰ: *{n_banks}*"
            )
        else:
            header = (
                f"✅ *ГКБ прочитан!*\n\n"
                f"👤 ФИО: *{name}*\n"
                f"🪪 ИИН: *{iin}*"
                + (f"\n📞 Тел.: *{phone}*" if phone else "")
                + f"\n\n📊 Активных кредитов: *{n_cr}*  |  Банков/МФО: *{n_banks}*"
            )

        if credits:
            gkb_txt = format_gkb(parsed)
            q = "👇 *По какому банку составить заявление?*" if lang=="ru" else "👇 *Қай банкке өтініш?*"

            # Отправляем заголовок отдельно
            await message.answer(header, parse_mode="Markdown")

            # Разбиваем gkb_txt на части по 3800 символов если длинный
            MAX_LEN = 3800
            chunks = []
            current = ""
            for line in gkb_txt.split("\n"):
                if len(current) + len(line) + 1 > MAX_LEN:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current = (current + "\n" + line) if current else line
            if current:
                chunks.append(current)

            # Отправляем части списка банков
            for i, chunk in enumerate(chunks):
                await message.answer(chunk, parse_mode="Markdown")

            # Вопрос + кнопки — отдельным сообщением
            await message.answer(q, parse_mode="Markdown", reply_markup=kb_gkb(credits, lang))
            await state.set_state(Form.pick_banks)
        else:
            await message.answer(
                header + "\n\n⚠️ Банки/МФО в отчёте не найдены. Введите название банка вручную:"
                if lang=="ru" else header + "\n\n⚠️ Банктер табылмады. Банк атауын енгізіңіз:",
                parse_mode="Markdown", reply_markup=kb_back(lang)
            )
            await state.update_data(manual_bank=True)
            await state.set_state(Form.ask_name)
        return

    # ── Файл не распознан ────────────────────────────────────
    name = parsed.get("full_name", "")
    iin  = parsed.get("iin", "")

    if doc_type in ("restr", "zero_change"):
        info = ("\n👤 " + name if name else "") + ("\n🪪 " + iin if iin else "")
        await message.answer(
            f"⚠️ ГКБ-отчёт не распознан.{info}\n\nВведите данные вручную:"
            if lang=="ru" else f"⚠️ МКБ есебі танылмады.{info}\nДеректерді қолмен енгізіңіз."
        )
        await state.update_data(parsed=parsed)
        await _start_manual(message, state, lang, parsed)
    else:
        await message.answer(
            "⚠️ Документ не распознан. Загрузите нужный PDF или нажмите 🏠 Главное меню."
            if lang=="ru" else "⚠️ Құжат танылмады."
        )

@router.message(Form.upload_file)
async def upload_wrong(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = gl(data)
    txt  = (message.text or "").lower().strip()
    if txt in ("нет", "жоқ", "/нет", "/жоқ"):
        await state.update_data(parsed={})
        await _start_manual(message, state, lang, {})
        return
    await message.answer(
        "📎 Отправьте *PDF-файл документом*, а не фото или текст."
        if lang=="ru" else "📎 *PDF-файлды* құжат ретінде жіберіңіз.",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
# ВЫБОР БАНКОВ ИЗ ГКБ
# ══════════════════════════════════════════════════════════════

@router.message(Form.pick_banks)
async def pick_banks(message: Message, state: FSMContext):
    data     = await state.get_data()
    lang     = gl(data)
    doc_type = data.get("doc_type", "restr")
    parsed   = data.get("parsed", {})
    credits  = parsed.get("credits", [])
    text     = (message.text or "").strip()

    if text in ("✅ Все банки", "✅ Барлық банктер"):
        # Группируем кредиты по банку — каждый уникальный банк → одна запись со всеми договорами
        bank_groups = {}
        for cr in credits:
            bd = cr.get("bank_data")
            if not bd:
                continue
            bank_key = bd.get("bin") or bd.get("ru")
            if bank_key not in bank_groups:
                bank_groups[bank_key] = {"bank_data": bd, "contracts": []}
            bank_groups[bank_key]["contracts"].append(cr)

        banks_with_amounts = []
        total_amount = 0
        for group in bank_groups.values():
            contracts = group["contracts"]
            total = sum(
                int(str(c.get("remaining_amount") or c.get("loan_amount") or 0).replace(",","").replace(" ",""))
                for c in contracts
            )
            banks_with_amounts.append({
                "bank_data": group["bank_data"],
                "loan_amount": total,
                "contracts": contracts,
            })
            total_amount += total

        if total_amount > 0:
            parsed["loan_amount"] = total_amount
        await state.update_data(banks_with_amounts=banks_with_amounts, parsed=parsed)
        await _after_bank(message, state, lang, parsed, doc_type)
        return

    # Конкретный банк — собираем ВСЕ кредиты этого банка
    clean = text.replace("🏦 ", "").strip()
    all_matched = [cr for cr in credits if clean.lower() in cr["bank"].lower()]
    if all_matched and all_matched[0].get("bank_data"):
        bank_data = all_matched[0]["bank_data"]
        total_amt = sum(
            int(str(cr.get("remaining_amount") or cr.get("loan_amount") or 0).replace(",","").replace(" ",""))
            for cr in all_matched
        )
        parsed["loan_amount"] = total_amt if total_amt else (
            all_matched[0].get("remaining_amount") or all_matched[0].get("loan_amount") or 0
        )
        parsed["selected_contracts"] = all_matched  # сохраняем все договора банка

        # Если несколько договоров — показываем сводку
        if len(all_matched) > 1:
            lines = []
            if lang == "ru":
                lines.append(f"📋 *По банку {bank_data['ru']} найдено {len(all_matched)} договора:*\n")
            else:
                lines.append(f"📋 *{bank_data['ru']} банкі бойынша {len(all_matched)} шарт табылды:*\n")
            for i, cr in enumerate(all_matched, 1):
                num = cr.get("contract_number", "—")
                amt = cr.get("remaining_amount") or cr.get("loan_amount") or 0
                try:
                    amt_str = f"{int(str(amt).replace(',','').replace(' ','')):,}" if amt else "—"
                except Exception:
                    amt_str = str(amt)
                lines.append(f"*{i}. Договор №{num}* — {amt_str} тг")
            if lang == "ru":
                lines.append(f"\n💰 *Итого: {parsed['loan_amount']:,} тг*")
                lines.append("_Заявление будет составлено по всем договорам._")
            else:
                lines.append(f"\n💰 *Барлығы: {parsed['loan_amount']:,} тг*")
                lines.append("_Барлық шарттар бойынша өтініш жасалады._")
            await message.answer("\n".join(lines), parse_mode="Markdown")

        await state.update_data(
            banks_list=[bank_data],
            banks_with_amounts=[{
                "bank_data": bank_data,
                "loan_amount": parsed["loan_amount"],
                "contracts": all_matched,
            }],
            parsed=parsed
        )
        await _after_bank(message, state, lang, parsed, doc_type)
    else:
        await message.answer("⚠️ Выберите банк из списка выше." if lang=="ru" else "⚠️ Тізімнен таңдаңыз.")

async def _after_bank(message, state, lang, parsed, doc_type):
    """После выбора банка: реструктуризация — спрашиваем срок → причину, нуль — сразу подтверждение."""
    data = await state.get_data()
    if doc_type == "restr":
        await state.update_data(parsed=parsed)
        await state.set_state(Form.ask_months)
        loan = parsed.get("loan_amount", "")
        hint = f"\n_(Долг из ГКБ: {int(str(loan).replace(',','').replace(' ','')):,} тг)_" if loan else ""
        await message.answer(
            f"📅 *На сколько месяцев растянуть выплаты?*{hint}\n"
            "_Введите число, например: 24_"
            if lang=="ru" else
            f"📅 *Қанша айға созғыңыз?*{hint}\n_Мысалы: 24_",
            parse_mode="Markdown", reply_markup=kb_back(lang)
        )
    else:
        # Изменение нуля — без вопросов
        await state.update_data(parsed=parsed)
        await _show_confirm(message, state, data, lang, parsed)


# ══════════════════════════════════════════════════════════════
# СРОК РЕСТРУКТУРИЗАЦИИ (после выбора банка из ГКБ или ручного ввода)
# ══════════════════════════════════════════════════════════════

@router.message(Form.ask_months)
async def got_months(message: Message, state: FSMContext):
    data   = await state.get_data()
    lang   = gl(data)
    parsed = data.get("parsed", {})
    txt    = (message.text or "").strip().replace(" ", "")
    try:
        months = int(txt)
        assert 1 <= months <= 120
    except Exception:
        await message.answer(
            "⚠️ Введите число от 1 до 120, например: *24*"
            if lang=="ru" else "⚠️ 1-ден 120-ға дейін сан: *24*",
            parse_mode="Markdown"
        )
        return
    parsed["months"] = str(months)
    try:
        amount  = int(str(parsed.get("loan_amount", "0")).replace(",", "").replace(" ", ""))
        monthly = round(amount / months)
        parsed["payment"] = str(monthly)
        calc_txt = (
            f"💡 *Расчёт:* {amount:,} тг ÷ {months} мес. = *~{monthly:,} тг/мес.*\n"
            "_Итоговый платёж устанавливает банк._\n\n"
        )
    except Exception:
        calc_txt = ""
    await state.update_data(parsed=parsed)
    await state.set_state(Form.ask_reason)
    await message.answer(
        calc_txt + "📝 *Выберите причину финансовых трудностей:*\n"
        "_(Бот вставит развёрнутый текст в заявление)_"
        if lang=="ru" else calc_txt + "📝 *Себепті таңдаңыз:*",
        parse_mode="Markdown", reply_markup=kb_reason(lang)
    )


# ══════════════════════════════════════════════════════════════
# РУЧНОЙ ВВОД ФИО / ИИН
# ══════════════════════════════════════════════════════════════

async def _start_manual(message, state, lang, parsed):
    if not parsed.get("full_name"):
        await state.set_state(Form.ask_name)
        await message.answer("👤 Введите ФИО полностью:" if lang=="ru" else "👤 ТАӘ толық:", reply_markup=kb_back(lang))
    elif not parsed.get("iin"):
        await state.set_state(Form.ask_iin)
        await message.answer("🪪 ИИН (12 цифр):" if lang=="ru" else "🪪 ЖСН (12 сан):", reply_markup=kb_back(lang))
    else:
        await state.set_state(Form.ask_reason)
        data = await state.get_data()
        await message.answer(
            "📝 *Причина:*" if lang=="ru" else "📝 *Себеп:*",
            parse_mode="Markdown", reply_markup=kb_reason(lang)
        )

@router.message(Form.ask_name)
async def got_name(message: Message, state: FSMContext):
    data   = await state.get_data()
    lang   = gl(data)
    parsed = data.get("parsed", {})
    if not message.text:
        await message.answer("⚠️ Введите ФИО текстом."); return
    # Если это ручной ввод банка (manual_bank=True) — обрабатываем иначе
    if data.get("manual_bank"):
        b = find_bank(message.text.strip())
        if b:
            await state.update_data(banks_list=[b], manual_bank=False)
            doc_type = data.get("doc_type", "restr")
            if doc_type == "restr":
                # После банка для ручного сценария спрашиваем сумму долга
                await state.set_state(Form.ask_iin)  # переиспользуем как ask_loan_amount
                await state.update_data(manual_amount=True)
                await message.answer(
                    "💰 Введите сумму задолженности (тенге), например: *500000*"
                    if lang=="ru" else "💰 Берешек сомасын енгізіңіз (теңге): *500000*",
                    parse_mode="Markdown", reply_markup=kb_back(lang)
                )
            else:
                await _after_bank(message, state, lang, parsed, doc_type)
        else:
            await message.answer(
                "⚠️ Банк не найден. Попробуйте: *Kaspi, Народный, ЦентрКредит, Forte, Home Credit*"
                if lang=="ru" else "⚠️ Банк табылмады. Мысалы: *Kaspi, Халық*",
                parse_mode="Markdown"
            )
        return
    parsed["full_name"] = message.text.strip()
    await state.update_data(parsed=parsed)
    await state.set_state(Form.ask_iin)
    await message.answer("🪪 ИИН (12 цифр):" if lang=="ru" else "🪪 ЖСН (12 сан):", reply_markup=kb_back(lang))

@router.message(Form.ask_iin)
async def got_iin(message: Message, state: FSMContext):
    data   = await state.get_data()
    lang   = gl(data)
    parsed = data.get("parsed", {})

    # Если это ручной ввод суммы долга (manual_amount=True)
    if data.get("manual_amount"):
        raw = (message.text or "").strip().replace(" ", "").replace(",", "")
        try:
            amount = int(float(raw))
            assert amount > 0
        except Exception:
            await message.answer(
                "⚠️ Введите сумму цифрами, например: *500000*"
                if lang=="ru" else "⚠️ Санмен: *500000*",
                parse_mode="Markdown"
            )
            return
        parsed["loan_amount"] = amount
        await state.update_data(parsed=parsed, manual_amount=False)
        # Теперь спрашиваем срок
        await state.set_state(Form.ask_months)
        await message.answer(
            "📅 *На сколько месяцев растянуть выплаты?*\n_Введите число, например: 24_"
            if lang=="ru" else "📅 *Қанша айға?* _Мысалы: 24_",
            parse_mode="Markdown", reply_markup=kb_back(lang)
        )
        return

    iin    = (message.text or "").strip()
    if not iin.isdigit() or len(iin) != 12:
        await message.answer("⚠️ ИИН — ровно 12 цифр." if lang=="ru" else "⚠️ ЖСН дәл 12 сан."); return
    parsed["iin"] = iin
    await state.update_data(parsed=parsed)
    doc_type = data.get("doc_type", "restr")
    if doc_type == "restr":
        # Нужно ещё спросить банк (вручную) и сумму
        await state.set_state(Form.ask_name)  # переиспользуем как ask_bank_manual
        await state.update_data(manual_bank=True, parsed=parsed)
        await message.answer(
            "🏦 Введите название банка/МФО (например: *Kaspi*, *Народный*, *Forte*):"
            if lang=="ru" else "🏦 Банк/МҚҰ атауын енгізіңіз:",
            parse_mode="Markdown", reply_markup=kb_back(lang)
        )
    else:
        await _show_confirm(message, state, data, lang, parsed)

# ══════════════════════════════════════════════════════════════
# ПРИЧИНА (только для реструктуризации)
# ══════════════════════════════════════════════════════════════

@router.message(Form.ask_reason)
async def got_reason(message: Message, state: FSMContext):
    data   = await state.get_data()
    lang   = gl(data)
    parsed = data.get("parsed", {})
    text   = (message.text or "").strip()

    # Переводим казахскую кнопку в русский ключ (если нужно)
    ru_key = REASON_KZ_TO_RU.get(text, text)

    if text in ("✏️ Своя причина", "✏️ Өз себебім"):
        await message.answer(
            "✏️ Напишите причину своими словами:" if lang=="ru" else "✏️ Себепті жазыңыз:",
            reply_markup=kb_back(lang)
        )
        return  # ждём следующее сообщение в том же state

    if ru_key in REASON_TEMPLATES and REASON_TEMPLATES[ru_key]:
        parsed["reason"] = REASON_TEMPLATES[ru_key]
    else:
        parsed["reason"] = text  # свободный ввод

    await state.update_data(parsed=parsed)
    await _show_confirm(message, state, data, lang, parsed)

# ══════════════════════════════════════════════════════════════
# ПОДТВЕРЖДЕНИЕ
# ══════════════════════════════════════════════════════════════

async def _show_confirm(message, state, data, lang, parsed):
    banks_list = data.get("banks_list", [])
    doc_type   = data.get("doc_type", "restr")
    banks_txt  = ", ".join(b["ru"] for b in banks_list) if banks_list else "—"

    lines = [
        "📋 *Данные для заявления:*\n",
        f"📄 Тип: *{DOC_NAMES.get(doc_type, doc_type)}*",
        f"👤 ФИО: *{parsed.get('full_name','—')}*",
        f"🪪 ИИН: *{parsed.get('iin','—')}*",
    ]
    if banks_txt != "—":
        lines.append(f"🏦 Кредитор: *{banks_txt}*")

    if doc_type == "cancel_in":
        if parsed.get("creditor_name"):
            lines.append(f"🏢 Кредитор: *{parsed['creditor_name']}*")
        if parsed.get("notary_name"):
            lines.append(f"⚖️ Нотариус: *{parsed['notary_name']}*")
        if parsed.get("contract_number"):
            lines.append(f"📄 Договор: №{parsed['contract_number']} от {parsed.get('contract_date','—')}")
        if parsed.get("total_amount"):
            lines.append(f"🔴 Сумма взыскания: *{parsed['total_amount']:,} тг*")

    elif doc_type == "cancel_court":
        if parsed.get("plaintiff"):
            lines.append(f"🏢 Взыскатель: *{parsed['plaintiff']}*")
        if parsed.get("court_name"):
            lines.append(f"🏛 Суд: *{parsed['court_name']}*")
        if parsed.get("case_number"):
            lines.append(f"📄 Дело №{parsed['case_number']}")
        if parsed.get("loan_amount"):
            lines.append(f"💰 Сумма: *{parsed['loan_amount']:,} тг*")

    elif doc_type == "restr":
        if parsed.get("loan_amount"):
            try: lines.append(f"💰 Долг: *{int(str(parsed['loan_amount']).replace(',','').replace(' ','')):,} тг*")
            except: pass
        if parsed.get("months"):
            lines.append(f"📅 Срок: *{parsed['months']} мес.*")
        if parsed.get("payment"):
            try: lines.append(f"💳 Платёж: *~{int(str(parsed['payment']).replace(',','').replace(' ','')):,} тг/мес.*")
            except: pass

    lines.append("\n✅ Создать заявление?" if lang=="ru" else "\n✅ Өтініш жасайық па?")
    await state.set_state(Form.confirm)
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=kb_confirm(lang))

# ══════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ ДОКУМЕНТА
# ══════════════════════════════════════════════════════════════

@router.message(Form.confirm, F.text.in_(CONFIRM_BUTTONS))
async def confirmed(message: Message, state: FSMContext):
    data               = await state.get_data()
    lang               = gl(data)
    parsed             = data.get("parsed", {})
    banks_list         = data.get("banks_list", [])
    banks_with_amounts = data.get("banks_with_amounts", [])  # для "Все банки"
    doc_type           = data.get("doc_type", "restr")

    # Для ИН/ИЛ — банк из parsed
    if not banks_list and not banks_with_amounts:
        creditor = parsed.get("creditor_name") or parsed.get("plaintiff", "")
        b = find_bank(creditor) if creditor else None
        banks_list = [b] if b else [{
            "ru": creditor or "Кредитор", "kz": creditor or "Кредитор",
            "bin": parsed.get("creditor_bin", "___"),
            "address": "___", "email": "___",
        }]

    await message.answer("⏳ Создаю документ..." if lang=="ru" else "⏳ Жасалуда...")

    generated = 0
    emails    = []

    # Если "Все банки" — берём banks_with_amounts, иначе banks_list
    if banks_with_amounts:
        iter_banks = banks_with_amounts  # [{bank_data: ..., loan_amount: ...}]
    else:
        iter_banks = [{"bank_data": b, "loan_amount": parsed.get("loan_amount")} for b in banks_list]

    for item in iter_banks:
        bank = item["bank_data"] if "bank_data" in item else item
        # Для каждого банка подставляем его персональную сумму и договора
        per_parsed = dict(parsed)
        if item.get("loan_amount"):
            per_parsed["loan_amount"] = item["loan_amount"]
            # Пересчитываем платёж если есть месяцы
            months_val = per_parsed.get("months")
            if months_val:
                try:
                    per_parsed["payment"] = str(round(int(item["loan_amount"]) / int(months_val)))
                except Exception:
                    pass
        # Передаём список договоров этого банка в генератор
        if item.get("contracts"):
            per_parsed["selected_contracts"] = item["contracts"]
        try:
            if doc_type == "restr":
                buf   = gen_restr(per_parsed, bank)
                fname = f"Реструктуризация_{bank['ru'][:20]}.docx"
            elif doc_type == "cancel_in":
                buf   = gen_otmena_in(per_parsed, bank)
                fname = f"Отмена_ИН_{bank['ru'][:20]}.docx"
            elif doc_type == "cancel_court":
                buf   = gen_otmena_suda(per_parsed, bank)
                fname = f"Отмена_решения_{bank['ru'][:20]}.docx"
            elif doc_type == "zero_change":
                buf   = gen_izmenenie_nulya(per_parsed, bank)
                fname = f"Изменение_нуля_{bank['ru'][:20]}.docx"
            else:
                buf   = gen_restr(per_parsed, bank)
                fname = f"Заявление_{bank['ru'][:20]}.docx"

            await message.answer_document(
                BufferedInputFile(buf.read(), filename=fname),
                caption=f"📄 {bank['ru']}"
            )
            e = bank.get("email", "")
            if e and e != "___":
                emails.append((bank["ru"], e))
            generated += 1
        except Exception as e:
            logger.error(f"Gen {bank.get('ru','?')}: {e}", exc_info=True)

    # Инструкции в чате (не в документе)
    tip = ""
    if doc_type == "cancel_in":
        tip = (
            "\n\n📌 *Как подать возражение:*\n"
            "1. Распечатайте и подпишите документ.\n"
            "2. Подайте лично нотариусу ИЛИ отправьте почтой с уведомлением.\n"
            "3. Можно направить на e-mail нотариуса.\n"
            "⏰ *Срок: 10 рабочих дней* с момента получения ИН.\n"
            "📌 Нотариус обязан вынести постановление об отмене в течение *3 рабочих дней*."
        )
    elif doc_type == "cancel_court":
        tip = (
            "\n\n📌 *Как подать ходатайство:*\n"
            "1. Распечатайте и подпишите.\n"
            "2. Подайте в канцелярию суда, вынесшего решение.\n"
            "3. Получите входящий штамп на своей копии."
        )
    elif doc_type == "restr" and emails:
        e_lines = "\n".join(f"  • {n}: `{e}`" for n, e in emails)
        tip = f"\n\n📧 *Отправьте на e-mail банка:*\n{e_lines}"
    elif doc_type == "zero_change" and emails:
        e_lines = "\n".join(f"  • {n}: `{e}`" for n, e in emails)
        tip = (
            f"\n\n📧 *Отправьте кредитору:*\n{e_lines}\n"
            "📌 Ответ в течение *15 рабочих дней* (ст. 24 Закона «О кредитных бюро»)."
        )

    disclaimer = (
        "\n\n⚠️ _Бот не является юридической службой и не несёт ответственности за результат рассмотрения заявления. "
        "Документы носят рекомендательный характер._"
        if lang=="ru" else
        "\n\n⚠️ _Бот заңдық қызмет емес және өтінішті қарау нәтижесіне жауапты емес. "
        "Құжаттар ұсыным сипатында._"
    )
    done = (
        f"✅ *Заявление готово!*{tip}{disclaimer}\n\nДля нового заявления — /start"
        if lang=="ru" else
        f"✅ *Өтініш дайын!*{tip}{disclaimer}\n\nЖаңа өтініш — /start"
    )

    await state.clear()
    await state.update_data(lang=lang)
    await state.set_state(Form.menu)
    await message.answer(done, parse_mode="Markdown", reply_markup=kb_menu(lang))

# ══════════════════════════════════════════════════════════════
# FALLBACK
# ══════════════════════════════════════════════════════════════

@router.message()
async def fallback(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("lang"):
        await state.clear()
        await state.set_state(Form.lang)
        await message.answer("👋 Выберите язык:", reply_markup=kb_lang())
        return
    lang = gl(data)
    await message.answer(
        "Выберите действие 👇" if lang=="ru" else "Әрекет таңдаңыз 👇",
        reply_markup=kb_menu(lang)
    )
