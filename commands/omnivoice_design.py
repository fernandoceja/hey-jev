"""Conservative, original prose-to-public-API tag mapping (stdlib, Python 3.9).

First match in source order wins per category. Longer phrases win ties;
moderate-pitch synonyms are fallback only when no stronger pitch occurs.
Ignored includes conflicting and unsupported words; common glue is omitted.
"""
from dataclasses import dataclass
import re
from typing import List, Optional


@dataclass
class DesignResult:
    instruct: Optional[str]
    tags: List[str]
    ignored: List[str]
    message: str


CATEGORIES = {
    'gender': ['male', 'female'],
    'age': ['child', 'teenager', 'young adult', 'middle-aged', 'elderly'],
    'pitch': ['very low pitch', 'low pitch', 'moderate pitch', 'high pitch', 'very high pitch'],
    'style': ['whisper'],
    'accent': [a + ' accent' for a in ('american', 'british', 'australian', 'chinese',
               'canadian', 'indian', 'korean', 'portuguese', 'russian', 'japanese')],
}
SYNONYMS = {
    'female': ('woman', 'girl', 'lady', 'she', 'her', 'feminine', 'mother', 'grandma'),
    'male': ('man', 'boy', 'guy', 'he', 'him', 'masculine', 'father', 'grandpa'),
    'child': ('kid', 'little', 'young child'),
    'teenager': ('teen',),
    'young adult': ('young', 'youthful'),
    'middle-aged': ('mature', 'adult', 'middle aged'),
    'elderly': ('old', 'aged', 'grandmother', 'grandfather', 'senior'),
    'low pitch': ('deep', 'bass', 'baritone', 'low', 'warm', 'rich', 'husky', 'gravelly'),
    'moderate pitch': ('calm', 'gentle', 'neutral', 'narrator', 'storyteller', 'soft spoken', 'soft-spoken'),
    'high pitch': ('bright', 'high', 'squeaky', 'chirpy', 'light'),
    'very low pitch': ('very deep', 'very low'),
    'very high pitch': ('very high',),
    'whisper': ('whispering', 'hushed', 'breathy'),
    'british accent': ('british', 'english', 'uk', 'london'),
    'american accent': ('american',),
    'australian accent': ('aussie', 'australian'),
    'portuguese accent': ('portuguese', 'brazilian'),
}


def describe_to_tags(description):
    if not isinstance(description, str):
        raise TypeError('description must be str')
    source = re.sub(r'\s+', ' ', description.lower().replace('，', ',')).strip()
    matches = []
    for category, tags in CATEGORIES.items():
        for tag in tags:
            aliases = [tag]
            aliases.extend(SYNONYMS.get(tag, ()))
            if category == 'accent':
                aliases.append(tag.split()[0])
            for alias in filter(None, aliases):
                for match in re.finditer(r'\b' + re.escape(alias) + r'\b', source):
                    matches.append((match.start(), -len(alias), match.end(), category, tag))
    matches.sort()
    strong_pitch = any(m[3] == 'pitch' and m[4] != 'moderate pitch' for m in matches)
    chosen, covered, tags = {}, set(), []
    for start, _, end, category, tag in matches:
        if any(i in covered for i in range(start, end)):
            continue
        if (category == 'pitch' and tag == 'moderate pitch' and strong_pitch
                and source[start:end] != 'moderate pitch'):
            continue
        if category in chosen and chosen[category] != tag:
            continue
        if category not in chosen:
            chosen[category] = tag
            tags.append(tag)
        covered.update(range(start, end))
    ignored = []
    glue = {'a', 'an', 'the', 'and', 'with', 'voice', 'of', 'in', 'is', 'who', 'sounds', 'like'}
    for match in re.finditer(r"\b[\w'-]+\b", source):
        word = match.group()
        if not any(i in covered for i in range(*match.span())) and word not in glue and word not in ignored:
            ignored.append(word)
    message = 'Mapped to: ' + ', '.join(tags) if tags else 'No supported tags; will use the default voice'
    if ignored:
        message += '. Ignored: ' + ', '.join(ignored) + ' (OmniVoice voice design only supports gender, age, pitch, whisper and supported accents)'
    return DesignResult(', '.join(tags) or None, tags, ignored, message)
