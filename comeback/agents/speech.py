"""Azure AI Speech (neural text-to-speech) for spoken catch-ups and recaps.

Uses the same Microsoft Foundry (Azure AI Services) resource as the LLM: the key
works for the Speech REST endpoint of its region. Audio files are cached on disk
by hash(voice, text); the demo's files are committed, so offline mode (judges,
public deployment) plays real neural voices without any Azure call.
"""

import hashlib
import logging
import os
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
from dotenv import load_dotenv

from comeback.agents.llm import ROOT, LLMMode

log = logging.getLogger(__name__)

AUDIO_DIR = ROOT / "data" / "audio"
AUDIO_URL_PREFIX = "/media/audio"
VOICES = {  # language → (locale, neural voice): one commentator-style voice per language
    "en": ("en-GB", "en-GB-RyanNeural"),
    "fr": ("fr-FR", "fr-FR-HenriNeural"),
    "es": ("es-ES", "es-ES-AlvaroNeural"),
}
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"


class SpeechGateway:
    """Synthesises (or finds in the cache) the audio for a text in a fan's language."""

    def __init__(self, audio_dir: Path = AUDIO_DIR) -> None:
        load_dotenv(ROOT / ".env")
        self.mode = LLMMode(os.getenv("LLM_MODE", "offline").lower())
        self.key = os.getenv("SPEECH_KEY") or os.getenv("FOUNDRY_API_KEY", "")
        self.region = os.getenv("SPEECH_REGION", "switzerlandnorth")
        self.audio_dir = audio_dir

    @staticmethod
    def audio_id(text: str, lang: str) -> str:
        voice = VOICES.get(lang, VOICES["en"])[1]
        return hashlib.sha256(f"{voice}\n{text}".encode()).hexdigest()[:24]

    def path(self, text: str, lang: str) -> Path:
        return self.audio_dir / f"{self.audio_id(text, lang)}.mp3"

    def url_if_cached(self, text: str, lang: str) -> str | None:
        path = self.path(text, lang)
        return f"{AUDIO_URL_PREFIX}/{path.name}" if path.exists() else None

    async def audio_url(self, text: str, lang: str) -> str | None:
        """URL of the spoken text; synthesised now in live/record mode, None if unavailable."""
        cached = self.url_if_cached(text, lang)
        if cached or self.mode is LLMMode.OFFLINE or not self.key or not text:
            return cached
        locale, voice = VOICES.get(lang, VOICES["en"])
        ssml = (f'<speak version="1.0" xml:lang="{locale}"><voice name="{voice}">'
                f'<prosody rate="+6%">{escape(text)}</prosody></voice></speak>')
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1",
                    headers={"Ocp-Apim-Subscription-Key": self.key, "Content-Type": "application/ssml+xml",
                             "X-Microsoft-OutputFormat": OUTPUT_FORMAT, "User-Agent": "comeback"},
                    content=ssml.encode("utf-8"),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("speech synthesis failed: %s", exc)
            return None
        path = self.path(text, lang)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return f"{AUDIO_URL_PREFIX}/{path.name}"
