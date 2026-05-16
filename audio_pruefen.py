import json
import subprocess
import sys
import termios
import tty
from pathlib import Path


AUDIO_FOLDER = "audio"
STATE_FILE = ".audio_pruefen_state.json"
PLAYER_COMMAND = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]


def clear_screen():
    print("\033[2J\033[H", end="")


def list_audio_files(folder):
    return sorted(Path(folder).glob("*.mp3"), key=lambda path: path.name.lower())


def load_reviewed_files():
    state_path = Path(STATE_FILE)
    if not state_path.exists():
        return set()

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return set()

    reviewed_files = state.get("reviewed_files", [])
    return set(reviewed_files)


def save_reviewed_files(reviewed_files):
    state = {
        "reviewed_files": sorted(reviewed_files),
    }
    Path(STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def display_word(index, total, audio_path):
    word = audio_path.stem.replace("_", " ")
    clear_screen()
    print(f"Wort {index}/{total}")
    print("=" * 60)
    print()
    print(word)
    print()
    print("=" * 60)
    print("Tasten: [K] behalten  [L] löschen  [R] erneut abspielen  [Q] beenden")


def start_playback(audio_path):
    return subprocess.Popen(
        PLAYER_COMMAND + [str(audio_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_playback(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()


def read_single_key():
    file_descriptor = sys.stdin.fileno()
    original_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        key = sys.stdin.read(1)
        if key == "\x03":
            raise KeyboardInterrupt
        return key.lower()
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, original_settings)


def review_audio_files():
    all_audio_files = list_audio_files(AUDIO_FOLDER)
    if not all_audio_files:
        print(f"Keine MP3-Dateien in '{AUDIO_FOLDER}' gefunden.")
        return

    existing_names = {audio_path.name for audio_path in all_audio_files}
    reviewed_files = {name for name in load_reviewed_files() if name in existing_names}
    save_reviewed_files(reviewed_files)

    audio_files = [audio_path for audio_path in all_audio_files if audio_path.name not in reviewed_files]
    if not audio_files:
        print("Keine ungeprüften MP3-Dateien mehr vorhanden.")
        print(f"Wenn du neu beginnen willst, lösche '{STATE_FILE}'.")
        return

    current_index = 0

    while current_index < len(audio_files):
        audio_path = audio_files[current_index]
        display_word(current_index + 1, len(audio_files), audio_path)
        playback_process = start_playback(audio_path)

        while True:
            key = read_single_key()

            if key == "k":
                stop_playback(playback_process)
                reviewed_files.add(audio_path.name)
                save_reviewed_files(reviewed_files)
                current_index += 1
                break

            if key == "l":
                stop_playback(playback_process)
                audio_path.unlink(missing_ok=True)
                reviewed_files.discard(audio_path.name)
                save_reviewed_files(reviewed_files)
                audio_files.pop(current_index)
                print(f"\nGelöscht: {audio_path.name}")
                break

            if key == "r":
                stop_playback(playback_process)
                playback_process = start_playback(audio_path)
                continue

            if key == "q":
                stop_playback(playback_process)
                print("\nPrüfung beendet.")
                return

        if not audio_files:
            clear_screen()
            print("Alle MP3-Dateien wurden bearbeitet.")
            return

    clear_screen()
    print("Prüfung abgeschlossen. Keine weiteren MP3-Dateien mehr vorhanden.")


if __name__ == "__main__":
    try:
        review_audio_files()
    except KeyboardInterrupt:
        print("\nPrüfung beendet.")
