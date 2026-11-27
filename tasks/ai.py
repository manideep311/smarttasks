import re
from datetime import date, timedelta

WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
WEEKDAY_PATTERN = '|'.join(WEEKDAYS)

LEAD_IN = re.compile(
    r"^(?:please\s+)?(?:remind\s+me\s+to|remember\s+to|don['’]t\s+forget\s+to|i\s+need\s+to|i\s+have\s+to|need\s+to)\s+",
    re.IGNORECASE,
)
RECURRING_WEEKDAY = re.compile(rf'\b(?:on\s+)?every\s+({WEEKDAY_PATTERN})\b', re.IGNORECASE)
RECURRENCE_RULES = [
    (re.compile(r'\b(?:of\s+)?every\s+day\b|\bdaily\b', re.IGNORECASE), 'daily'),
    (re.compile(r'\b(?:of\s+)?every\s+week\b|\bweekly\b', re.IGNORECASE), 'weekly'),
    (re.compile(r'\b(?:of\s+)?every\s+month\b|\bmonthly\b', re.IGNORECASE), 'monthly'),
    (re.compile(r'\b(?:of\s+)?every\s+year\b|\byearly\b|\bannually\b', re.IGNORECASE), 'yearly'),
]
ISO_DATE = re.compile(r'\b(?:on\s+|by\s+|due\s+)?(\d{4}-\d{2}-\d{2})\b', re.IGNORECASE)
DAY_AFTER_TOMORROW = re.compile(r'\b(?:on\s+|by\s+)?(?:the\s+)?day\s+after\s+tomorrow\b', re.IGNORECASE)
TOMORROW = re.compile(r'\b(?:on\s+|by\s+)?tomorrow\b', re.IGNORECASE)
TODAY = re.compile(r'\b(?:on\s+|by\s+)?(?:today|tonight)\b', re.IGNORECASE)
IN_DAYS = re.compile(r'\bin\s+(\d{1,3})\s+(days?|weeks?)\b', re.IGNORECASE)
NEXT_WEEK = re.compile(r'\bnext\s+week\b', re.IGNORECASE)
WEEKDAY = re.compile(rf'\b(?:on\s+|by\s+|next\s+|this\s+)?({WEEKDAY_PATTERN})\b', re.IGNORECASE)
ORDINAL_DAY = re.compile(
    r'\b(?:on\s+|by\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b(?:\s+of\s+(?:the|each)\s+month)?',
    re.IGNORECASE,
)
TRAILING_WORDS = re.compile(r'\s+(?:on|by|at|due|of|the|every)$', re.IGNORECASE)
SPLIT_PATTERN = re.compile(r'\s*(?:,|;|\band\s+then\b|\bthen\b|\band\b)\s*', re.IGNORECASE)


def next_weekday(today, weekday, allow_today=False):
    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0 and not allow_today:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def next_day_of_month(today, day):
    if not 1 <= day <= 31:
        return None
    year, month = today.year, today.month
    for _ in range(13):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate is not None and candidate >= today:
            return candidate
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return None


def remove_match(text, match):
    return text[:match.start()] + ' ' + text[match.end():]


def find_due_date(text, today):
    match = ISO_DATE.search(text)
    if match:
        try:
            due = date.fromisoformat(match.group(1))
        except ValueError:
            due = None
        return due, remove_match(text, match)
    match = DAY_AFTER_TOMORROW.search(text)
    if match:
        return today + timedelta(days=2), remove_match(text, match)
    match = TOMORROW.search(text)
    if match:
        return today + timedelta(days=1), remove_match(text, match)
    match = TODAY.search(text)
    if match:
        return today, remove_match(text, match)
    match = IN_DAYS.search(text)
    if match:
        amount = int(match.group(1))
        days = amount * 7 if match.group(2).lower().startswith('week') else amount
        return today + timedelta(days=days), remove_match(text, match)
    match = NEXT_WEEK.search(text)
    if match:
        return today + timedelta(days=7), remove_match(text, match)
    match = WEEKDAY.search(text)
    if match:
        weekday = WEEKDAYS.index(match.group(1).lower())
        return next_weekday(today, weekday), remove_match(text, match)
    match = ORDINAL_DAY.search(text)
    if match:
        return next_day_of_month(today, int(match.group(1))), remove_match(text, match)
    return None, text


def clean_title(text):
    title = re.sub(r'\s+', ' ', text).strip(' ,.;:!?-')
    previous = None
    while title != previous:
        previous = title
        title = TRAILING_WORDS.sub('', title).strip(' ,.;:!?-')
    return title[:1].upper() + title[1:]


def parse_task_text(text, today):
    original = text.strip()
    working = LEAD_IN.sub('', original)
    recurrence = None
    due_date = None

    match = RECURRING_WEEKDAY.search(working)
    if match:
        recurrence = 'weekly'
        due_date = next_weekday(today, WEEKDAYS.index(match.group(1).lower()), allow_today=True)
        working = remove_match(working, match)
    else:
        for pattern, value in RECURRENCE_RULES:
            match = pattern.search(working)
            if match:
                recurrence = value
                working = remove_match(working, match)
                break

    if due_date is None:
        due_date, working = find_due_date(working, today)

    title = clean_title(working)[:200].strip() or clean_title(original)[:200].strip()

    return {
        'title': title,
        'description': original,
        'due_date': due_date.isoformat() if due_date else None,
        'recurrence': recurrence,
    }


def break_down_task(task):
    titles = []
    for source in (task.description, task.title):
        parts = [part.strip(' .,;:!?') for part in SPLIT_PATTERN.split(source or '')]
        parts = [part for part in parts if len(part) > 1]
        if len(parts) >= 2:
            titles = parts
            break
    if not titles:
        name = task.title.strip().rstrip('.')
        titles = [f'Prepare: {name}', f'Work on: {name}', f'Review: {name}']
    due_date = task.due_date.isoformat() if task.due_date else None
    return [
        {
            'title': (title[:1].upper() + title[1:])[:200],
            'description': f'Subtask of "{task.title}"',
            'due_date': due_date,
            'priority': task.priority,
        }
        for title in titles
    ]
