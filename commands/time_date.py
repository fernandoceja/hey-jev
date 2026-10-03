"""Local time and date replies."""
from datetime import datetime
from .textutil import _clock, _ordinal

def speak_time():
    now = datetime.now().astimezone()
    return f"It's {_clock(now)}, {now:%A %B} {_ordinal(now.day)}."


def speak_date():
    now = datetime.now().astimezone()
    return f"Today is {now:%A, %B} {_ordinal(now.day)}, {now.year}."
