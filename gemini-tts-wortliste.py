import json
import re
import subprocess
import tempfile
import time
from pathlib import Path

from google import genai
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.genai import types


CREDENTIALS_PATH = "key.json"
IMPORT_WORDS_DIR = Path("data/import_words")
OUTPUT_FOLDER = "audio"
PROJECT_LOCATION = "us-central1"
MODEL_NAME = "gemini-2.5-pro-tts"
DEFAULT_VOICE = "Achernar"
DEFAULT_LANGUAGE_CODE = "de-DE"
DEFAULT_PROMPT = "Lies langsam und deutlich"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
PAUSE_BETWEEN_REQUESTS_SECONDS = 2
INITIAL_429_WAIT_SECONDS = 60
MAX_429_WAIT_SECONDS = 300


POS_BY_HEADING = {
    "nomen": "nomen",
    "namenwörter": "nomen",
    "verben": "verb",
    "tunwörter": "verb",
    "adjektive": "adjektiv",
    "wiewörter": "adjektiv",
}


def remove_markdown(text):
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    return text.strip()


def remove_articles(text):
    segments = [segment.strip() for segment in text.split("/")]
    cleaned_segments = []
    for segment in segments:
        cleaned = re.sub(r"^(der|die|das)\s+", "", segment.strip(), flags=re.IGNORECASE)
        cleaned_segments.append(cleaned.strip())
    return " / ".join(segment for segment in cleaned_segments if segment)


def build_storage_term(raw_term):
    storage_term = remove_markdown(raw_term)
    storage_term = storage_term.split("/", 1)[0].strip()
    storage_term = storage_term.split("(", 1)[0].strip()
    storage_term = remove_articles(storage_term)
    storage_term = re.sub(r"\s+", " ", storage_term).strip()
    return storage_term


def build_spoken_text(raw_term):
    spoken_text = remove_markdown(raw_term)
    spoken_text = remove_articles(spoken_text)
    spoken_text = re.sub(r"\(([^)]*)\)", r" \1", spoken_text)
    spoken_text = re.sub(r"\s*/\s*", " oder ", spoken_text)
    spoken_text = re.sub(r"\s+", " ", spoken_text).strip()
    return spoken_text


def make_safe_name(term):
    safe_name = re.sub(r"[^\w\s-]", "", term, flags=re.UNICODE).strip()
    safe_name = re.sub(r"\s+", "_", safe_name)
    return safe_name


def detect_pos(heading_text):
    normalized = remove_markdown(heading_text).lower()
    for key, value in POS_BY_HEADING.items():
        if key in normalized:
            return value
    return None


def parse_wordlist(filepath):
    if not Path(filepath).exists():
        print(f"❌ Datei '{filepath}' nicht gefunden.")
        return []

    entries = []
    current_pos = None

    with open(filepath, "r", encoding="utf-8") as file_handle:
        for line_number, line in enumerate(file_handle, 1):
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("#"):
                heading_text = stripped.lstrip("#").strip()
                new_pos = detect_pos(heading_text)
                if new_pos:
                    current_pos = new_pos
                continue

            if current_pos is None:
                continue

            storage_term = build_storage_term(stripped)
            spoken_text = build_spoken_text(stripped)
            safe_name = make_safe_name(storage_term)

            if not storage_term or not spoken_text or not safe_name:
                print(f"⚠️ Überspringe unklare Zeile {line_number}: {stripped}")
                continue

            entries.append(
                {
                    "pos": current_pos,
                    "raw_term": stripped,
                    "storage_term": storage_term,
                    "spoken_text": spoken_text,
                    "safe_name": safe_name,
                }
            )

    return entries


def parse_import_words(import_dir):
    import_dir = Path(import_dir)
    if not import_dir.exists():
        print(f"❌ Verzeichnis '{import_dir}' nicht gefunden.")
        return []

    entries = []
    for json_path in sorted(import_dir.glob("*.json")):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            print(f"⚠️ Überspringe ungültige JSON-Datei {json_path.name}: {error}")
            continue

        raw_term = str(payload.get("lemma", "")).strip()
        if not raw_term:
            print(f"⚠️ Überspringe Datei ohne lemma: {json_path.name}")
            continue

        storage_term = build_storage_term(raw_term)
        spoken_text = build_spoken_text(raw_term)
        safe_name = make_safe_name(storage_term)
        if not storage_term or not spoken_text or not safe_name:
            print(f"⚠️ Überspringe unklaren Eintrag in {json_path.name}: {raw_term}")
            continue

        entries.append(
            {
                "source_file": json_path.name,
                "raw_term": raw_term,
                "storage_term": storage_term,
                "spoken_text": spoken_text,
                "safe_name": safe_name,
            }
        )

    return entries


def load_credentials():
    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=SCOPES,
    )
    credentials.refresh(Request())

    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as file_handle:
        credential_data = json.load(file_handle)

    project_id = credential_data.get("project_id")
    if not project_id:
        raise RuntimeError(f"In {CREDENTIALS_PATH} wurde keine project_id gefunden.")

    return credentials, project_id


def create_vertex_client(credentials, project_id):
    return genai.Client(
        vertexai=True,
        credentials=credentials,
        project=project_id,
        location=PROJECT_LOCATION,
    )


def build_tts_config():
    return types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            language_code=DEFAULT_LANGUAGE_CODE,
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=DEFAULT_VOICE,
                )
            ),
        ),
    )


def extract_audio_part(response):
    for candidate in response.candidates or []:
        if not candidate.content or not candidate.content.parts:
            continue
        for part in candidate.content.parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data, (part.inline_data.mime_type or "")
    return None, None


def parse_sample_rate(mime_type):
    match = re.search(r"rate=(\d+)", mime_type or "", flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 24000


def convert_pcm_to_mp3(pcm_bytes, mime_type, output_path):
    sample_rate = parse_sample_rate(mime_type)

    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(pcm_bytes)

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "s16le",
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                "-i",
                str(temp_path),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(output_path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"ffmpeg-Konvertierung fehlgeschlagen: {error.stderr.strip()}") from error
    finally:
        temp_path.unlink(missing_ok=True)


def synthesize_to_mp3(client, spoken_text, output_path):
    prompt_and_text = f"{DEFAULT_PROMPT}: {spoken_text}"
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt_and_text,
        config=build_tts_config(),
    )

    audio_bytes, mime_type = extract_audio_part(response)
    if not audio_bytes:
        raise RuntimeError("Keine Audiodaten in der Vertex-Antwort gefunden.")

    convert_pcm_to_mp3(audio_bytes, mime_type, output_path)


def main():
    output_folder = Path(OUTPUT_FOLDER)
    output_folder.mkdir(parents=True, exist_ok=True)

    entries = parse_import_words(IMPORT_WORDS_DIR)
    if not entries:
        print("⚠️ Keine verwertbaren Wörter gefunden.")
        return

    credentials, project_id = load_credentials()
    client = create_vertex_client(credentials, project_id)

    print(f"🎙️ Starte Vertex-TTS-Generierung für {len(entries)} JSON-Einträge")
    print(f"📂 Zielordner: {output_folder}")
    print(f"📚 Quelle: {IMPORT_WORDS_DIR}")
    print(f"🗣️ Stimme: {DEFAULT_VOICE} | Sprache: {DEFAULT_LANGUAGE_CODE}")
    print(f"🤖 Modell: {MODEL_NAME}")
    print("-" * 60)

    for index, entry in enumerate(entries, 1):
        output_path = output_folder / f"{entry['safe_name']}.mp3"

        if output_path.exists():
            print(f"[{index}/{len(entries)}] ⏩ Überspringe '{entry['storage_term']}' (MP3 existiert bereits)")
            continue

        print(f"[{index}/{len(entries)}] 🎧 Erzeuge MP3 für '{entry['spoken_text']}'")

        retry_wait_seconds = INITIAL_429_WAIT_SECONDS

        while True:
            try:
                if not credentials.valid or credentials.expired:
                    credentials.refresh(Request())

                synthesize_to_mp3(
                    client=client,
                    spoken_text=entry["spoken_text"],
                    output_path=output_path,
                )
                print(f"✅ Gespeichert: {output_path}")

                if PAUSE_BETWEEN_REQUESTS_SECONDS > 0:
                    print(f"⏳ Kurze Pause: {PAUSE_BETWEEN_REQUESTS_SECONDS}s")
                    time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)
                break
            except KeyboardInterrupt:
                print("\n⏹️ Abbruch durch Benutzer. Bereits erzeugte MP3-Dateien bleiben erhalten.")
                return
            except Exception as error:
                error_text = str(error)
                if "429" in error_text and "RESOURCE_EXHAUSTED" in error_text:
                    print(
                        f"⏳ Quota erreicht bei '{entry['storage_term']}'. "
                        f"Warte {retry_wait_seconds}s und versuche es erneut..."
                    )
                    time.sleep(retry_wait_seconds)
                    retry_wait_seconds = min(retry_wait_seconds * 2, MAX_429_WAIT_SECONDS)
                    continue

                print(f"❌ Fehler bei '{entry['storage_term']}': {error}")
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Abbruch durch Benutzer. Bereits erzeugte MP3-Dateien bleiben erhalten.")
