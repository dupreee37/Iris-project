"""Prueba optativa Windows: WAV sintético -> STT local -> diálogo -> WAV.

Ejecutar: python tests/check_local_speech.py
No abre micrófono, no reproduce sonido y no consulta APIs.
"""
from pathlib import Path
import wave

from iris.dialogue import DemoDialogue
from iris.local_speech import LocalRecognizer, render_wave


def main():
    root = Path("work/voice-validation")
    root.mkdir(parents=True, exist_ok=True)
    recognizer = LocalRecognizer("work/models/vosk-model-small-es-0.42")
    dialogue = DemoDialogue()
    replies = []
    for index, text in enumerate(["Iris, necesito que investigues algo por mi.", "Sobre baterias para un robot."]):
        source = root / f"input-{index}.wav"
        render_wave(text, source)
        with wave.open(str(source), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            data = wav.readframes(wav.getnframes()) + b"\0" * 64000
        words = []
        for offset in range(0, len(data), 640):
            phrase = recognizer.accept(data[offset:offset + 640])
            if phrase:
                words.append(phrase)
        reply = dialogue.hear(" ".join(words))
        replies.append(reply)
        assert reply.text
        render_wave(reply.text, root / f"reply-{index}.wav")
        recognizer.reset()
    assert "tema" in replies[0].text
    assert replies[1].query and "robot" in replies[1].query
    print("PASS: audio sintético en español -> reconocimiento local -> aclaración -> tema -> respuesta hablada a WAV.")


if __name__ == "__main__":
    main()
