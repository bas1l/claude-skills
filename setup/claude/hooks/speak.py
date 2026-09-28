"""Speak text from a file using edge-tts + Windows audio playback."""
import asyncio
import re
import sys
import tempfile
import os


def sanitize_markdown(text):
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"^[|].*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\-\*\+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\n", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()[:2000]


async def speak(text, voice="en-US-JennyNeural", rate="+0%"):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate)
    tmp = tempfile.mktemp(suffix=".mp3")
    try:
        await comm.save(tmp)
        from edge_playback.win32_playback import play_mp3_win32
        play_mp3_win32(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    text_file = sys.argv[1] if len(sys.argv) > 1 else None
    voice = sys.argv[2] if len(sys.argv) > 2 else "en-US-JennyNeural"
    rate = sys.argv[3] if len(sys.argv) > 3 else "+0%"
    do_sanitize = "--sanitize" in sys.argv
    if not text_file or not os.path.exists(text_file):
        sys.exit(1)
    with open(text_file, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        sys.exit(0)
    if do_sanitize:
        text = sanitize_markdown(text)
    if not text:
        sys.exit(0)
    asyncio.run(speak(text, voice, rate))
