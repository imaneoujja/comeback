/* Speech in the fan's language. On iOS, utterance.lang alone is not enough: the
 * default (English) voice reads French text with an English accent. So we pick a
 * voice explicitly from speechSynthesis.getVoices(), waiting for "voiceschanged"
 * when the list is still empty, and only fall back to utterance.lang. */

const REGION = { en: ["en-GB", "en-US"], fr: ["fr-FR", "fr-CA"], es: ["es-ES", "es-MX"] };
const supported = () => "speechSynthesis" in window;

let voicesPromise = null;

function loadVoices() {
  if (!supported()) return Promise.resolve([]);
  const now = speechSynthesis.getVoices();
  if (now.length) return Promise.resolve(now);
  voicesPromise ||= new Promise((resolve) => {
    const done = () => resolve(speechSynthesis.getVoices());
    speechSynthesis.addEventListener("voiceschanged", done, { once: true });
    setTimeout(done, 2000);              // some browsers never fire the event
  }).finally(() => { voicesPromise = null; });
  return voicesPromise;
}

/** Best installed voice for ``lang`` ("en" | "fr" | "es"), or null. */
export async function pickVoice(lang) {
  const voices = await loadVoices();
  const prefix = (lang || "en").toLowerCase();
  const norm = (v) => v.lang.replace("_", "-").toLowerCase();
  for (const region of REGION[prefix] || []) {
    const exact = voices.filter((v) => norm(v) === region.toLowerCase());
    const best = exact.find((v) => v.localService) || exact[0];
    if (best) return best;
  }
  const any = voices.filter((v) => norm(v).startsWith(prefix));
  return any.find((v) => v.default) || any.find((v) => v.localService) || any[0] || null;
}

/** Speak ``text`` with a voice of ``lang``. Resolves when speech starts (or is skipped). */
export async function speak(text, lang) {
  if (!supported() || !text) return;
  const voice = await pickVoice(lang);
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  if (voice) { u.voice = voice; u.lang = voice.lang; } else { u.lang = (REGION[lang] || REGION.en)[0]; }
  u.rate = 1.02;
  speechSynthesis.speak(u);
}

/** iOS only allows speech after a user gesture: call this from a tap handler. */
export function unlockSpeech() {
  if (!supported()) return;
  speechSynthesis.speak(new SpeechSynthesisUtterance(" "));
  loadVoices();
}

export const stopSpeech = () => supported() && speechSynthesis.cancel();
