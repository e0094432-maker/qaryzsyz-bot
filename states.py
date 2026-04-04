from aiogram.fsm.state import State, StatesGroup

class Form(StatesGroup):
    lang            = State()  # выбор языка
    menu            = State()  # главное меню
    upload_file     = State()  # ожидание PDF
    pick_banks      = State()  # выбор банков из ГКБ
    ask_name        = State()  # ручной ввод ФИО
    ask_iin         = State()  # ручной ввод ИИН
    ask_months      = State()  # срок реструктуризации
    ask_reason      = State()  # причина финансовых трудностей
    confirm         = State()  # подтверждение → генерация
    bankruptcy_sub  = State()  # подменю банкротства (Критерии / Инструкция)
    zero_warning    = State()  # предупреждение о нулевой просрочке
