"""
PDF-парсер для @Qaryzsyz_qoqam_Bot
Поддерживает: ГКБ-отчёт (русский + казахский), Исполнительная надпись (ИН), Исполнительный лист (ИЛ)

Версия v10:
- Поддержка казахского ГКБ (Жеке кредиттік есеп / ЖСН / Міндеттеме N)
- Исправлен detect_type: ГКБ определяется первым
- Паттерны сумм под формат /валюта: 1141514.00 KZT
- Блочный парсинг по «Обязательство N» и «Міндеттеме N»
- Только действующие обязательства (завершённые исключены)
"""
import re, io, logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ══════════════════════════════════════
# PDF → текст
# ══════════════════════════════════════

def extract_text(file_bytes: bytes) -> str:
    try:
        import pypdf
        r = pypdf.PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in r.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)
    except Exception as e:
        logger.error(f"PDF extract error: {e}")
        return ""


def normalize_text(text: str) -> str:
    lines = text.split("\n")
    result = []
    buf = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buf:
                result.append(" ".join(buf))
                buf = []
            result.append("")
        else:
            buf.append(stripped)
    if buf:
        result.append(" ".join(buf))
    out = []
    prev_empty = False
    for line in result:
        if line == "":
            if not prev_empty:
                out.append(line)
            prev_empty = True
        else:
            out.append(line)
            prev_empty = False
    return "\n".join(out)


# ══════════════════════════════════════
# Определение типа документа
# ══════════════════════════════════════

def detect_type(text: str) -> str:
    """
    ГКБ проверяется ПЕРВЫМ — в нём встречается «исполнительная надпись»
    в блоке взыскания, что раньше давало ложный тип «ин».
    """
    t = text.lower()

    # ── 1. ГКБ (русский + казахский) ─────────────────────────
    gkb_strong = [
        # Русский
        "персональный кредитный отчет",
        "персональныйкредитныйотчет",
        "государственное кредитное бюро",
        "государственноекредитноебюро",
        "первое кредитное бюро",
        "кредитный отчёт", "кредитный отчет",
        # Казахский
        "жеке кредиттік есеп",
        "жекекредиттікесеп",
        "мемлекеттік кредиттік бюро",
        "мемлекеттіккредиттікбюро",
        "бірінші кредиттік бюро",
    ]
    gkb_indirect = [
        # Русский
        "фаза контракта", "фазаконтракта",
        "просроченных взносов /валюта",
        "количество дней просрочки",
        "подробнаяинформацияподействующим",
        # Казахский
        "міндеттеме",
        "мерзіміөткенкүндерсаны",
        "мерзіміөткенжарналарсомасы",
        "жснн", "жсн:",
    ]
    if any(k in t for k in gkb_strong):
        return "gkb"
    if sum(1 for k in gkb_indirect if k in t) >= 2:
        return "gkb"

    # ── 2. ИН ────────────────────────────────────────────────
    in_strong = [
        "е-нотариат", "e-notary", "enotary",
        "статьи 92-1", "ст. 92-1",
        "зарегистрировано в реестре нотариальных",
        "распоряжаюсь взыскать",
    ]
    has_in_phrase = "исполнительная надпись" in t or "исполнительной надписи" in t
    in_hits = sum(1 for k in in_strong if k in t)
    if has_in_phrase and in_hits >= 1:
        return "in"
    if in_hits >= 2:
        return "in"

    # ── 3. ИЛ ────────────────────────────────────────────────
    il_kw = [
        "исполнительный лист", "исполнительного листа",
        "дата вступления судебного акта",
        "судебных исполнителей",
        "гражданского процессуального кодекса",
    ]
    if any(k in t for k in il_kw):
        return "il"

    return "unknown"


# ══════════════════════════════════════
# Утилиты
# ══════════════════════════════════════

def _clean(s: str) -> str:
    return " ".join(s.replace("\n", " ").split()).strip()


def _parse_amount(s: str):
    """Парсит число: 415513.26 → 415513, 249481,33 → 249481, 415 513 → 415513"""
    try:
        cleaned = re.sub(r"[\s\xa0]", "", str(s))
        # Заменяем запятую-разделитель дробей на точку (249481,33 → 249481.33)
        # Но только если формат ЧИСЛО,ДВЕ_ЦИФРЫ (дробная часть)
        cleaned = re.sub(r",(\d{1,2})$", r".\1", cleaned)
        # Убираем оставшиеся запятые (разделители тысяч)
        cleaned = cleaned.replace(",", "")
        if "." in cleaned:
            return int(float(cleaned))
        return int(cleaned)
    except Exception:
        return None


def _v(d, *keys, default="___"):
    for k in keys:
        v = d.get(k)
        if v:
            return str(v).strip()
    return default


# ══════════════════════════════════════
# ПАРСИНГ ГКБ (русский + казахский)
# ══════════════════════════════════════

def parse_gkb(text: str) -> dict:
    """
    Парсит ГКБ отчёт на русском или казахском языке.

    Русский формат:
      Обязательство N → ... → Кредитор: ... → суммы

    Казахский формат:
      Міндеттеме N → ... → Кредитор: ... → суммы
      ФИО: Тегі / Аты / Әкесінің аты
      ИИН: ЖСН
      Суммы: Шарттың жалпы сомасы, Мерзімі өткен жарналар сомасы, Мерзімі өткен күндер саны
    """
    from banks import BANKS

    d = {"doc_type": "gkb", "credits": []}
    t_low = text.lower()

    # Определяем язык отчёта
    is_kz = "жекекредиттікесеп" in t_low or "міндеттеме" in t_low or "жсн:" in t_low

    # ── ФИО ──────────────────────────────────────────────────
    if is_kz:
        # Казахский: Тегі / Аты / Әкесінің аты
        # Паттерны работают и в raw (многострочном) и в normalized (однострочном) тексте.
        # Используем lookahead на следующий казахский ключ вместо \n как терминатор.
        _KZ_NEXT = r"(?=\s*(?:Аты|ЖСН|Туған|Азамат|Жыны|Несие|\n|$))"
        _KZ_NEXT_ATY = r"(?=\s*(?:Әке|ЖСН|Туған|Азамат|\n|$))"
        _KZ_NEXT_OTH = r"(?=\s*(?:ЖСН|Туған|Азамат|\n|$))"
        _KZ_NAME = r"[А-ЯЁа-яёA-Za-zА-ӨҰҚҒҺа-өұқғһ\-]+"

        fam = re.search(r"Тегі[:\s\xa0]+" + f"({_KZ_NAME})" + _KZ_NEXT, text, re.I)
        nm  = re.search(r"\bАты[:\s\xa0]+" + f"({_KZ_NAME})" + _KZ_NEXT_ATY, text, re.I)
        oth = re.search(r"Әкесінің\s*аты[:\s\xa0]+" + f"({_KZ_NAME})" + _KZ_NEXT_OTH, text, re.I)
        if fam and nm:
            parts = [fam.group(1).strip(), nm.group(1).strip()]
            if oth:
                parts.append(oth.group(1).strip())
            d["full_name"] = _clean(" ".join(parts))
    else:
        # Русский
        fam = re.search(r"Фамилия[:\s\xa0]+([А-ЯЁа-яёA-Za-z][^\n\d:]{1,30}?)(?:\s*Имя|\s*ИИН|\n|$)", text, re.I)
        nm  = re.search(r"\bИмя[:\s\xa0]+([А-ЯЁа-яёA-Za-z][^\n\d:]{1,20}?)(?:\s*Отчество|\s*ИИН|\n|$)", text, re.I)
        oth = re.search(r"Отчество[:\s\xa0]+([А-ЯЁа-яёA-Za-z][^\n\d:]{1,20}?)(?:\s*ИИН|\n|$)", text, re.I)
        if fam and nm:
            parts = [fam.group(1).strip(), nm.group(1).strip()]
            if oth:
                parts.append(oth.group(1).strip())
            d["full_name"] = _clean(" ".join(parts))

    # ── ИИН / ЖСН ────────────────────────────────────────────
    m = re.search(r"(?:ИИН|ЖСН|IIN|ЖСН:)[:\s\xa0]*?(\d{12})", text)
    if not m:
        m = re.search(r"\b(\d{12})\b", text)
    if m:
        d["iin"] = m.group(1)

    # ── Телефон ───────────────────────────────────────────────
    m = re.search(
        r"(?:Моб\.?\s*тел\.?|Телефон|Ұялы\s*тел\.?|Ұялытел\.?)"
        r"[:\s\xa0]*(\+?[78][\d\s\-\(\)]{9,15})",
        text, re.I
    )
    if m:
        d["phone"] = re.sub(r"[\s\-\(\)]", "", m.group(1))[:12]

    # ══════════════════════════════════════════════════════════
    # НАХОДИМ СЕКЦИЮ ДЕЙСТВУЮЩИХ ОБЯЗАТЕЛЬСТВ
    # ══════════════════════════════════════════════════════════
    active_start = 0
    active_end = len(text)

    if is_kz:
        # Казахский: начало = ҚОЛДАНЫСТАҒЫ МІНДЕТТЕМЕЛЕР / ШАРТТАР
        # конец   = АЯҚТАЛҒАН МІНДЕТТЕМЕЛЕР / ШАРТТАР
        #
        # ВАЖНО: эти маркеры встречаются НЕСКОЛЬКО РАЗ в тексте — и в
        # сводной таблице (до активных блоков), и в заголовке секции.
        # Поэтому для маркера конца ищем ПЕРВОЕ вхождение ПОСЛЕ active_start,
        # а не просто первое вхождение в тексте.

        # ── Маркер начала активных ────────────────────────────
        for marker in [
            # с пробелами (нормальный pypdf)
            "қолданыстағы шарттар бойынша толық ақпарат",
            "қолданыстағы шарттар туралы толық ақпарат",
            "қолданыстағы міндеттемелер",
            "толық ақпарат қолданыстағы",
            # без пробелов (слитый pypdf)
            "қолданыстағышарттарбойыншатолықақпарат",
            "қолданыстағышарттартуралытолықақпарат",
            "қолданыстағыміндеттемелер",
            "толықақпарат",
        ]:
            idx = t_low.find(marker)
            if idx != -1:
                active_start = idx
                break

        # Фолбэк: если маркер начала не найден — ищем первый «Міндеттеме 1»
        if active_start == 0:
            m_fb = re.search(r"М[іi]ндеттеме\s*1\b", text, re.I)
            if m_fb:
                active_start = m_fb.start()

        # ── Маркер конца активных (первый ПОСЛЕ active_start) ─
        end_markers_kz = [
            # с пробелами
            "аяқталған шарттар туралы толық ақпарат",
            "аяқталған шарттар бойынша толық ақпарат",
            "аяқталған борыштық міндеттемелер туралы",
            "аяқталған міндеттемелер",
            # без пробелов
            "аяқталғаншарттартуралытолықақпарат",
            "аяқталғаншарттарбойыншатолықақпарат",
            "аяқталғанборыштықміндеттемелертуралы",
            "аяқталғанміндеттемелер",
            "аяқталғанмiндеттемелер",
        ]
        for marker in end_markers_kz:
            search_from = 0
            while True:
                idx = t_low.find(marker, search_from)
                if idx == -1:
                    break
                if idx > active_start:
                    active_end = idx
                    break
                search_from = idx + 1  # следующее вхождение
            if active_end < len(text):
                break
    else:
        # Русский
        for marker in [
            "подробная информация по действующим",
            "подробнаяинформацияподействующим",
        ]:
            idx = t_low.find(marker)
            if idx != -1:
                active_start = idx
                break
        for marker in [
            "подробная информация о завершенных",
            "подробнаяинформацияозавершенных",
            "подробная информация о завершённых",
        ]:
            idx = t_low.find(marker)
            if idx != -1 and idx > active_start:
                active_end = idx
                break

    active_text = text[active_start:active_end]

    # ══════════════════════════════════════════════════════════
    # БЛОКИ ОБЯЗАТЕЛЬСТВ
    # Русский: Обязательство N (слиплось: Обязательство1)
    # Казахский: Міндеттеме N (слиплось: Міндеттеме1)
    # ══════════════════════════════════════════════════════════
    if is_kz:
        obligation_re = re.compile(r"М[іi]ндеттеме\s*(\d+)", re.IGNORECASE)
    else:
        obligation_re = re.compile(r"Обязательство\s*(\d+)", re.IGNORECASE)

    matches = list(obligation_re.finditer(active_text))

    if matches:
        for i, m_obj in enumerate(matches):
            start = m_obj.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(active_text)
            block = active_text[start:end]
            # Пропускаем закрытые обязательства по статусу внутри блока
            if is_kz and _block_is_closed_kz(block):
                continue
            if not is_kz and _block_is_closed_ru(block):
                continue
            cr = _parse_gkb_block(block, BANKS, is_kz=is_kz)
            if cr:
                d["credits"].append(cr)
    else:
        d["credits"] = _parse_gkb_fallback(active_text, BANKS, is_kz=is_kz)

    return d


def _block_is_closed_kz(block: str) -> bool:
    """
    Возвращает True, если блок казахского обязательства является закрытым/завершённым.
    Казахские статусы закрытия: Жабық / Жабылған / Аяқталған / Тоқтатылған
    """
    b = block.lower()
    closed_statuses = [
        "жабық",       # закрыт
        "жабылған",    # закрытый
        "аяқталған",   # завершённый
        "тоқтатылған", # прекращённый
    ]
    # Ищем только рядом с меткой статуса договора
    status_match = re.search(
        r"шарт(?:тың)?\s*мәртебесі[:\s]*([^\n]{1,60})",
        b, re.I
    )
    if status_match:
        status_val = status_match.group(1).strip()
        return any(s in status_val for s in closed_statuses)
    # Запасной вариант: сам факт наличия слова «аяқталған» в начале блока (≤300 симв)
    return "аяқталған" in b[:300]


def _block_is_closed_ru(block: str) -> bool:
    """
    Возвращает True, если блок русского обязательства является закрытым/завершённым.
    Русские статусы закрытия: Закрыт / Погашен / Завершён / Прекращён
    """
    b = block.lower()
    closed_statuses = [
        "закрыт",
        "погашен",
        "завершён",
        "завершен",
        "прекращён",
        "прекращен",
        "исполнен",
    ]
    # Ищем только рядом с меткой "Статус договора"
    status_match = re.search(
        r"статус\s+договора[:\s]*([^\n]{1,60})",
        b, re.I
    )
    if status_match:
        status_val = status_match.group(1).strip()
        return any(s in status_val for s in closed_statuses)
    return False


def _parse_gkb_block(block: str, BANKS: dict, is_kz: bool = False) -> dict | None:
    """
    Парсит один блок обязательства.

    Русский формат ГКБ:
      Кредитор: АО "Kaspi Bank"
      Общая сумма договора /валюта: 1141514.00 KZT
      Сумма просроченных взносов /валюта: 415513.26 KZT
      Количество дней просрочки: 161

    Казахский формат ГКБ:
      Кредитор: АО "Kaspi Bank"
      Шарттың жалпы сомасы/валюта: 2043251.00 KZT
      Мерзімі өткен жарналар сомасы/валюта: 0.00 KZT
      Мерзімі өткен күндер саны: 0
    """
    cr = {}

    # ── Кредитор (одинаково в обоих языках) ──────────────────
    m = re.search(r"Кредитор:\s*(.+?)(?:\n|БИН:|БСН:|$)", block, re.I)
    if not m:
        # Нормализованный текст (пробелы слеплены)
        m = re.search(r"Кредитор:(.+?)(?:БИН|БСН|\n|$)", block, re.I)
    if not m:
        return None
    creditor_raw = _clean(m.group(1))
    creditor_lower = creditor_raw.lower()

    matched_bank = None
    for bank_key, bank in BANKS.items():
        for alias in bank["names"]:
            if alias.lower() in creditor_lower:
                matched_bank = bank
                break
        if matched_bank:
            break

    if matched_bank:
        cr["bank"] = matched_bank["ru"]
        cr["bank_data"] = matched_bank
    else:
        cr["bank"] = creditor_raw
        cr["bank_data"] = {"ru": creditor_raw, "kz": creditor_raw, "bin": "___", "email": "", "address": "___"}

    # ── Статус ───────────────────────────────────────────────
    if is_kz:
        m = re.search(r"Шарт(?:тың\s*|тың)мәртебесі[:\s]*(.+?)(?:\n|Келісімшарт)", block, re.I)
        if not m:
            m = re.search(r"Шарттың\s+мәртебесі[:\s]*(.+?)(?:\n|Келісімшарт)", block, re.I)
    else:
        m = re.search(r"Статус\s+договора:\s*(.+?)(?:\n|Признак)", block, re.I)
    if m:
        cr["status"] = _clean(m.group(1))

    # ── Дата выдачи ──────────────────────────────────────────
    if is_kz:
        date_pats = [
            r"Нақтыберукүні:\s*(\d{2}\.\d{2}\.\d{4})",
            r"Келісімшарттыңқолданылумерзімініңбасталукүні:\s*(\d{2}\.\d{2}\.\d{4})",
            r"Кредиткеөтінімберукүні:\s*(\d{2}\.\d{2}\.\d{4})",
        ]
    else:
        date_pats = [
            r"Дата\s+фактической\s+выдачи:\s*(\d{2}\.\d{2}\.\d{4})",
            r"Дата\s+начала\s+срока\s+действия\s+контракта:\s*(\d{2}\.\d{2}\.\d{4})",
            r"Дата\s+заявки\s+на\s+кредит:\s*(\d{2}\.\d{2}\.\d{4})",
        ]
    for pat in date_pats:
        m = re.search(pat, block, re.I)
        if m:
            cr["contract_date"] = m.group(1)
            break

    # ── Номер договора ────────────────────────────────────────
    if is_kz:
        m = re.search(r"Шарт\s*нөмірі[:\s]+(\S+)", block, re.I)
    else:
        m = re.search(r"Номер\s+договора:\s*(\S+)", block, re.I)
    if m:
        val = m.group(1).strip()
        if not re.match(r"\d{2}[./]\d{2}[./]\d{4}", val):
            cr["contract_number"] = val[:30]

    # ── Общая сумма договора ──────────────────────────────────
    if is_kz:
        loan_pats = [
            r"Шарттыңжалпысомасы/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Шарттың\s*жалпы\s*сомасы\s*/\s*валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Шарттың\s+жалпы\s+сомасы\s*/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Шарт\s+жалпы\s+сомасы[:\s]+([\d\s\xa0,]+\.?\d*)\s*KZT",
            r"жалпы\s+сомасы\s*/\s*валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
        ]
    else:
        loan_pats = [
            r"Общая\s+сумма\s+договора\s*/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Общая\s+сумма\s+договора[:\s]+([\d\s\xa0,]+\.?\d*)\s*(?:KZT|тенге|тг)",
            r"Общая\s+сумма\s+(?:займа|кредита)[:\s]+([\d\s\xa0,]+\.?\d*)\s*(?:KZT|тенге|тг)",
            r"Лимит\s+кредита[:\s]+([\d\s\xa0,]+\.?\d*)\s*(?:KZT|тенге|тг)",
        ]
    for pat in loan_pats:
        m = re.search(pat, block, re.I)
        if m:
            v = _parse_amount(m.group(1))
            if v and 1_000 < v < 2_000_000_000:
                cr["loan_amount"] = v
                break

    # ── Просроченная сумма ────────────────────────────────────
    if is_kz:
        overdue_pats = [
            r"Мерзіміөткенжарналарсомасы/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Мерзімі\s*өткен\s*жарналар\s*сомасы\s*/\s*валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Мерзімі\s+өткен\s+жарналар\s+сомасы\s*/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Мерзімі\s+өткен\s+жарналар\s+сомасы[:\s]+([\d\s\xa0,]+\.?\d*)\s*KZT",
            r"өткен\s+жарналар\s+сомасы\s*/\s*валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
        ]
    else:
        overdue_pats = [
            r"Сумма\s+просроченных\s+взносов\s*/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Сумма\s+просрочен\w+\s+(?:взносов|платежей)[:\s]+([\d\s\xa0,]+\.?\d*)\s*(?:KZT|тенге|тг)",
            r"Просроченн\w+\s+(?:баланс|сумма)[:\s]+([\d\s\xa0,]+\.?\d*)\s*(?:KZT|тенге|тг)",
        ]
    for pat in overdue_pats:
        m = re.search(pat, block, re.I)
        if m:
            v = _parse_amount(m.group(1))
            if v is not None and v >= 0:
                cr["overdue_amount"] = v
                break

    # ── Предстоящие платежи ───────────────────────────────────
    if is_kz:
        balance_pats = [
            r"Алдағытөлемдерсомасы/валюта\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Алдағы\s+төлемдер\s+сомасы[:\s]+([\d\s\xa0,]+\.?\d*)\s*KZT",
        ]
    else:
        balance_pats = [
            r"Сумма\s+предстоящих\s+платежей\s*/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
            r"Остаток\s+задолженности\s+по\s+договору\s*/валюта:\s*([\d\s\xa0]+\.?\d*)\s*KZT",
        ]
    for pat in balance_pats:
        m = re.search(pat, block, re.I)
        if m:
            v = _parse_amount(m.group(1))
            if v is not None and v > 0:
                cr["balance"] = v
                break

    # ── Количество дней просрочки ─────────────────────────────
    if is_kz:
        days_pats = [
            r"Мерзіміөткенкүндерсаны:\s*(\d+)",
            r"Мерзімі\s+өткен\s+күндер\s+саны[:\s]*(\d+)",
            r"өткен\s+күндер\s+саны[:\s]*(\d+)",
        ]
    else:
        days_pats = [
            r"Количество\s+дней\s+просрочки:\s*(\d+)",
            r"Дней\s+просрочки[:\s]*(\d+)",
        ]
    for pat in days_pats:
        m = re.search(pat, block, re.I)
        if m:
            try:
                days = int(m.group(1))
                if 0 <= days < 10000:
                    cr["overdue_days"] = days
            except Exception:
                pass
            break

    # ── Остаток долга (реальный) ──────────────────────────────
    # remaining = алдағы төлемдер (предстоящие) + мерзімі өткен (просрочка)
    # Это то, что реально осталось выплатить банку
    balance_val  = cr.get("balance", 0) or 0
    overdue_val  = cr.get("overdue_amount", 0) or 0
    remaining    = balance_val + overdue_val
    if remaining > 0:
        cr["remaining_amount"] = remaining
    elif cr.get("loan_amount"):
        # Фолбэк: если не можем посчитать — берём сумму договора
        cr["remaining_amount"] = cr["loan_amount"]

    # ── Аномалия ─────────────────────────────────────────────
    if cr.get("contract_date") and cr.get("overdue_days") is not None:
        for fmt in ("%d.%m.%Y", "%d-%m-%Y"):
            try:
                dt = datetime.strptime(cr["contract_date"], fmt)
                days_since = (datetime.now() - dt).days
                if days_since > 730 and cr["overdue_days"] < 10:
                    cr["anomaly"] = (
                        f"⚠️ Договор от {cr['contract_date']} "
                        f"({days_since // 365} г. назад), "
                        f"а просрочка {cr['overdue_days']} дн. — "
                        f"возможно данные обнулены!"
                    )
                break
            except ValueError:
                continue

    return cr


def _parse_gkb_fallback(text: str, BANKS: dict, is_kz: bool = False) -> list:
    """Фолбэк: ищем банки по позиции в тексте."""
    credits = []
    text_l = text.lower()
    bank_positions = []

    for bank_key, bank in BANKS.items():
        for alias in bank["names"]:
            idx = text_l.find(alias.lower())
            if idx != -1:
                bank_positions.append((idx, bank_key, bank))
                break

    bank_positions.sort(key=lambda x: x[0])
    seen = set()
    unique = []
    for item in bank_positions:
        if item[1] not in seen:
            seen.add(item[1])
            unique.append(item)

    lines = text.split("\n")
    lines_lower = [l.lower() for l in lines]

    def find_bank_line(alias_lower):
        for li, line in enumerate(lines_lower):
            if alias_lower in line:
                return li
        return 0

    bank_line_nums = []
    for idx_b, bank_key_b, bank_b in unique:
        for alias_b in bank_b["names"]:
            ln = find_bank_line(alias_b.lower())
            if ln > 0 or alias_b.lower() in lines_lower[0]:
                bank_line_nums.append((ln, bank_key_b, bank_b))
                break
    bank_line_nums.sort(key=lambda x: x[0])

    for i, (idx, bank_key, bank) in enumerate(unique):
        line_num = bank_line_nums[i][0] if i < len(bank_line_nums) else 0
        end_line = bank_line_nums[i + 1][0] if i + 1 < len(bank_line_nums) else len(lines)
        snippet = "\n".join(lines[line_num:end_line])
        cr = _parse_gkb_block(snippet, BANKS, is_kz=is_kz)
        if cr:
            credits.append(cr)

    return credits


def format_gkb(d: dict) -> str:
    credits = d.get("credits", [])
    if not credits:
        return "⚠️ Банки/МФО в отчёте не найдены."
    lines = []
    total_overdue = 0
    for i, cr in enumerate(credits, 1):
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append(f"🏦 {i}. *{cr['bank']}*")
        if cr.get("contract_number"):
            lines.append(f"   📄 Договор: {cr['contract_number']}")
        if cr.get("contract_date"):
            lines.append(f"   📅 Выдан: {cr['contract_date']}")
        if cr.get("loan_amount"):
            lines.append(f"   💵 Сумма займа: *{cr['loan_amount']:,} тг*")
        if cr.get("balance"):
            lines.append(f"   💰 Предстоящие: *{cr['balance']:,} тг*")
        if cr.get("overdue_amount") is not None:
            lines.append(f"   🔴 Просрочка: *{cr['overdue_amount']:,} тг*")
            total_overdue += cr["overdue_amount"]
        if cr.get("overdue_days") is not None:
            lines.append(f"   📆 Дней просрочки: *{cr['overdue_days']}*")
        if cr.get("anomaly"):
            lines.append(f"   {cr['anomaly']}")
        if not any(k in cr for k in ("loan_amount", "balance", "overdue_amount", "overdue_days")):
            lines.append("   ℹ️ Суммы не найдены — заполните вручную")
    lines.append("━━━━━━━━━━━━━━━━━━")
    if total_overdue > 0:
        lines.append(f"📊 *Итого просрочка: {total_overdue:,} тг*")
    return "\n".join(lines)


# ══════════════════════════════════════
# ПАРСИНГ ИН
# ══════════════════════════════════════

def parse_in(text: str) -> dict:
    d = {"doc_type": "in"}

    for pat in [
        r"взыскать[^с]{0,30}с\s+([А-ЯЁ][А-ЯЁа-яё]+\s+[А-ЯЁ][А-ЯЁа-яё]+(?:\s+[А-ЯЁ][А-ЯЁа-яё]+)?),?\s*\d{2}\.\d{2}",
        r"с\s+([А-ЯЁ]{2,}\s+[А-ЯЁ]{2,}\s+[А-ЯЁ]{2,}),?\s*\d{2}\.\d{2}\.\d{4}",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            candidate = _clean(m.group(1))
            if len(candidate.split()) >= 2 and not re.search(r"\d", candidate):
                d["full_name"] = candidate
                break

    m = re.search(r"Я,?\s+([А-ЯЁ]+\s+[А-ЯЁ]+\s+[А-ЯЁ]+),?\s+нотариус", text)
    if not m:
        m = re.search(r"Нотариус\s+([А-ЯЁ][А-ЯЁа-яё\s]+?)(?:\n|$)", text)
    if m:
        d["notary_name"] = _clean(m.group(1))

    m = re.search(r"нотариус\s+г(?:орода?)?\.\s*(\w+)", text, re.I)
    if m:
        d["notary_city"] = m.group(1).strip()

    m = re.search(r"(?:ИИН|ЖСН)[:\s]*(\d{12})", text)
    if not m:
        m = re.search(r"\b(\d{12})\b", text)
    if m:
        d["iin"] = m.group(1)

    # Адрес должника: захватываем до «в пользу» / «БИН» / конца строки
    # Исправлен баг: старый паттерн «съедал» имя кредитора → обрыв на «Микроф»
    m = re.search(
        r"местонахождение[:\s]+(.+?)(?:,?\s*в\s+пользу\b|\s+БИН\s+\d|\n|$)",
        text, re.I | re.DOTALL
    )
    if m:
        d["address"] = _clean(m.group(1)).rstrip(",").strip()

    for pat in [
        # Полное название до «(представитель» или «БИН ХХХХ»
        r"в\s+пользу\s+((?:Товарищество|ТОО|АО|ИП|ООО).{5,300}?)(?:\s*\(представитель|\s*БИН\s+\d{12})",
        # До запятой + БИН
        r"в\s+пользу\s+(.{5,300}?)(?:\s*,\s*БИН\s+\d{12}|\s+БИН\s+\d{12})",
        # До конца строки
        r"в\s+пользу\s+(.{5,200}?)(?:\n|$)",
    ]:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            cand = _clean(m.group(1)).strip('"').strip("'").rstrip(",")
            if len(cand.split()) >= 2 and len(cand) > 5:
                d["creditor_name"] = cand
                break

    m = re.search(r"БИН\s+(\d{12})", text)
    if m:
        d["creditor_bin"] = m.group(1)

    # Договор: №RC-9395310 или №RC- 9395310 (пробел) или просто №RC-9395310
    for cpat in [
        r"договору?\s*№\s*([A-Za-zА-ЯЁа-яё0-9\-/]+(?:\s*-\s*\d+)?)\s*,",
        r"договору?\s*№\s*([A-Za-zА-ЯЁа-яё0-9\-/\s]+?)(?:,|\s+задолженность|\s+за\s+период)",
        r"договор[уа]?\s*[№#]\s*([\w\-/\s]{3,30}?)(?:\s+от\s+\d|,|\s+задолженность)",
    ]:
        m = re.search(cpat, text, re.I)
        if m:
            val = re.sub(r"\s+", "", m.group(1)).strip(",-")
            if len(val) >= 3:
                d["contract_number"] = val
                break

    m = re.search(r"за\s+период\s+(\d{2}\.\d{2}\.\d{4})\s*[-–—]\s*(\d{2}\.\d{2}\.\d{4})", text, re.I)
    if m:
        d["period_from"] = m.group(1)
        d["period_to"]   = m.group(2)

    # Основной долг (поддержка форматов: 249481,33 и 249481.33 и 249 481)
    for pat in [
        r"задолженность\s+в\s+сумме\s+([\d\s\xa0]+[,.]\d{1,2})\s*тенге",
        r"задолженность\s+в\s+сумме\s+([\d\s\xa0]+)\s*тенге",
        r"сумму\s+задолженности\s+([\d\s\xa0,]+[,.]\d{1,2})\s*тенге",
        r"сумму\s+задолженности\s+([\d\s\xa0]+)\s*тенге",
        r"основной\s+долг[^.]*?([\d\s\xa0,]+[,.]\d{1,2})\s*тенге",
        r"взыскать[^.]*?([\d\s\xa0,]+[,.]\d{1,2})\s*тенге",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            v = _parse_amount(m.group(1))
            if v and v > 0:
                d["debt_amount"] = v
                break

    # Общая сумма (поддержка форматов: 255704.33 и 255704,33 и 255 704)
    for pat in [
        r"[Оо]бщая\s+сумма[^.]{0,50}составляет\s+([\d\s\xa0]+[,.]\d{1,2})\s*тенге",
        r"[Оо]бщая\s+сумма[^.]{0,50}составляет\s+([\d\s\xa0]+)\s*тенге",
        r"[Оо]бщая\s+сумма\s+задолженности[^.]*?([\d\s\xa0,]+[,.]\d{1,2})\s*тенге",
        r"[Оо]бщая\s+сумма\s+задолженности[^.]*?([\d\s\xa0]{4,})\s*тенге",
        r"Итого[^.]*?([\d\s\xa0,]+[,.]\d{1,2})\s*тенге",
        r"Итого[^.]*?([\d\s\xa0]{5,})\s*тенге",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            v = _parse_amount(m.group(1))
            if v and v > 0:
                d["total_amount"] = v
                break

    m = re.search(r"расходы\s+по\s+совершению[^.]*?в\s+сумме\s+([\d\s\xa0]+)\s*тенге", text, re.I)
    if m:
        v = _parse_amount(m.group(1))
        if v:
            d["notary_fee"] = v

    m = re.search(r"реестре\s+за\s+№\s*(\d+)", text, re.I)
    if m:
        d["reg_number"] = m.group(1)

    m = re.search(r"«(\d+)»\s+(\w+)\s+(\d{4})\s*(?:г|год)", text)
    if m:
        d["in_date"] = f"{m.group(1)} {m.group(2)} {m.group(3)} г."

    return d


def format_in(d: dict) -> str:
    lines = ["📋 *Исполнительная надпись:*\n"]
    if d.get("full_name"):
        lines.append(f"👤 Должник: *{d['full_name']}*")
    if d.get("iin"):
        lines.append(f"🪪 ИИН: *{d['iin']}*")
    if d.get("creditor_name"):
        lines.append(f"🏢 Кредитор: *{d['creditor_name']}*")
    if d.get("notary_name"):
        lines.append(f"⚖️ Нотариус: {d['notary_name']}")
    if d.get("notary_city"):
        lines.append(f"📍 Город: {d['notary_city']}")
    if d.get("contract_number"):
        lines.append(f"📄 Договор №{d['contract_number']} от {d.get('contract_date', '—')}")
    if d.get("period_from"):
        lines.append(f"📅 Период: {d['period_from']} — {d.get('period_to', '?')}")
    if d.get("debt_amount"):
        lines.append(f"💰 Основной долг: *{d['debt_amount']:,} тг*")
    if d.get("notary_fee"):
        lines.append(f"📝 Расходы нотариуса: {d['notary_fee']:,} тг")
    if d.get("total_amount"):
        lines.append(f"🔴 *Итого к взысканию: {d['total_amount']:,} тг*")
    if d.get("reg_number"):
        lines.append(f"🔢 Реестр: №{d['reg_number']}")
    if d.get("in_date"):
        lines.append(f"🗓 Дата ИН: {d['in_date']}")
    return "\n".join(lines)


# ══════════════════════════════════════
# ПАРСИНГ ИЛ
# ══════════════════════════════════════

def parse_il(text: str) -> dict:
    d = {"doc_type": "il"}

    m = re.search(r"([\w\s]+(?:районный|городской|областной)\s+суд)", text, re.I)
    if m:
        d["court_name"] = _clean(m.group(1))

    m = re.search(r"город\s+(\w+),?\s+улица|г\.\s*(\w+),?\s*ул\.", text, re.I)
    if m:
        d["court_city"] = _clean(m.group(1) or m.group(2) or "")

    m = re.search(r"№\s*([\d\-\/]+(?:-\d+)?)", text)
    if m:
        d["case_number"] = m.group(1).strip()

    m = re.search(r"(?:рассмотрев|рассмотрен)[^\n]*?(\d{2}\.\d{2}\.\d{4})", text, re.I)
    if m:
        d["case_date"] = m.group(1)

    m = re.search(r"Дата вступления[^\d]*(\d{2}\.\d{2}\.\d{4})", text, re.I)
    if m:
        d["enforce_date"] = m.group(1)

    m = re.search(r"\nк\s+([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s*\(Ф\.И\.О\.", text)
    if not m:
        m = re.search(r"ФИО:\s+([А-ЯЁ][а-яёА-ЯЁ\s\-]+?)(?:\n|Дата)", text)
    if m:
        d["full_name"] = _clean(m.group(1))

    m = re.search(r"ИИН[:\s]*(\d{12})", text)
    if m:
        d["iin"] = m.group(1)

    m = re.search(r"Фактический адрес:\s*([^\n]+)", text, re.I)
    if m:
        d["address"] = m.group(1).strip()[:150]

    m = re.search(r"по иску\s+([\w\s«»\"\'ТОО АО ЗАО ИП]+?)\s*\(Ф\.И\.О\.", text, re.I | re.DOTALL)
    if not m:
        m = re.search(r"Наименование компании:\s*(.+?)(?:\n|БИН)", text, re.I | re.DOTALL)
    if m:
        d["plaintiff"] = _clean(m.group(1))

    for pat in [
        r"сумму в размере\s+([\d\s\xa0]+)\s*\(",
        r"взыскать\s+с[^.]*?([\d\s\xa0]{5,})\s*тенге",
        r"основного\s+долга\s+в\s+размере\s+([\d\s\xa0]+)\s*тенге",
        r"задолженности\s+в\s+размере\s+([\d\s\xa0]+)\s*тенге",
        r"сумму\s+([\d\s\xa0]{5,})\s*\((?:сто|двес|триста|четыре|пять|шест|семь|восем|девять|один|два|три)",
    ]:
        m = re.search(pat, text, re.I | re.DOTALL)
        if m:
            v = _parse_amount(m.group(1))
            if v and v > 0:
                d["loan_amount"] = v
                break

    m = re.search(r"пеня\s+([\d\s\xa0]+)\s*\(", text, re.I)
    if m:
        v = _parse_amount(m.group(1))
        if v:
            d["penalty"] = v

    m = re.search(r"государственн\w+\s+пошлин\w+\s+(?:в размере\s+)?([\d\s\xa0]+)", text, re.I)
    if m:
        v = _parse_amount(m.group(1))
        if v:
            d["state_fee"] = v

    return d


def format_il(d: dict) -> str:
    lines = ["⚖️ *Исполнительный лист:*\n"]
    if d.get("court_name"):
        lines.append(f"🏛 Суд: *{d['court_name']}*")
    if d.get("case_number"):
        lines.append(f"📄 Дело №: *{d['case_number']}*")
    if d.get("case_date"):
        lines.append(f"📅 Дата решения: {d['case_date']}")
    if d.get("enforce_date"):
        lines.append(f"✅ Вступило в силу: {d['enforce_date']}")
    lines.append("")
    if d.get("plaintiff"):
        lines.append(f"🏢 Взыскатель: *{d['plaintiff']}*")
    if d.get("full_name"):
        lines.append(f"👤 Ответчик: *{d['full_name']}*")
    if d.get("iin"):
        lines.append(f"🪪 ИИН: *{d['iin']}*")
    lines.append("")
    if d.get("loan_amount"):
        lines.append(f"💰 Основной долг: *{d['loan_amount']:,} тг*")
    if d.get("penalty"):
        lines.append(f"📈 Пеня: {d['penalty']:,} тг")
    if d.get("state_fee"):
        lines.append(f"🏛 Госпошлина: {d['state_fee']:,} тг")
    total = sum(p for p in [d.get("loan_amount", 0), d.get("penalty", 0), d.get("state_fee", 0)] if p)
    if total > 0:
        lines.append(f"🔴 *Итого: {total:,} тг*")
    return "\n".join(lines)


# ══════════════════════════════════════
# ГЛАВНЫЕ ФУНКЦИИ
# ══════════════════════════════════════

def parse_document(text: str) -> dict:
    t = detect_type(text)
    if t == "in":
        return parse_in(text)
    elif t == "il":
        return parse_il(text)
    elif t == "gkb":
        return parse_gkb(text)
    else:
        d = {"doc_type": "unknown"}
        m = re.search(r"\b(\d{12})\b", text)
        if m:
            d["iin"] = m.group(1)
        m = re.search(r"([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)", text)
        if m:
            d["full_name"] = m.group(1)
        return d
