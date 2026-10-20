"""Translator: an English version of a fan's catch-up, for viewers who do not read its language.

Judges and studio staff may not read French or Spanish. The Storyteller writes for the
fan; the Translator gives an English rendering of that exact text. It is checked before
use: the same numbers and the same player and club names must appear in both texts,
otherwise no translation is shown (never a wrong one).
"""

import json
import re

from comeback.agents.llm import LLMGateway, LLMUnavailable, parse_json_reply

TRANSLATOR_INSTRUCTIONS = """You translate a football text written for a fan into natural English.
Keep every number, player name and club name exactly as written. Do not add, remove or
explain anything. Write JSON only: {"text": "..."}."""
_NUMBER = re.compile(r"\d+")


def faithful(original: str, english: str, names: set[str]) -> bool:
    """Same numbers, and every known name of the original also in the translation."""
    if sorted(_NUMBER.findall(original)) != sorted(_NUMBER.findall(english)):
        return False
    return all(name in english for name in names if name in original)


async def english_version(text: str, language: str, gateway: LLMGateway, names: set[str]) -> str | None:
    """English rendering of ``text`` (``None`` if already English, unavailable, or not faithful)."""
    if language == "en" or not text:
        return None
    try:
        reply = await gateway.ask("Translator", TRANSLATOR_INSTRUCTIONS,
                                  json.dumps({"language": language, "text": text}, ensure_ascii=False))
        english = str(parse_json_reply(reply.text)["text"]).strip()
    except (LLMUnavailable, ValueError, KeyError, TypeError):
        return None
    return english if faithful(text, english, names) else None
