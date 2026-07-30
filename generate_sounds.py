"""
Synthesizes short WAV sound effects for the Who Dis? bot's voice-channel
playback, using pure sine-wave tones -- stdlib only, no external audio
files, so there's zero licensing/sourcing risk.

Output: assets/sounds/{new_round,submit,round_win,game_win}.wav

Run:  python3 generate_sounds.py
"""
import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "assets" / "sounds"
OUT.mkdir(parents=True, exist_ok=True)

SAMPLE_RATE = 44100


def _tone(freq: float, duration: float, volume: float = 0.45, fade: float = 0.015) -> list:
    n = int(duration * SAMPLE_RATE)
    fade_n = max(1, int(fade * SAMPLE_RATE))
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        value = math.sin(2 * math.pi * freq * t)
        if i < fade_n:
            value *= i / fade_n
        elif i > n - fade_n:
            value *= (n - i) / fade_n
        samples.append(value * volume)
    return samples


def _silence(duration: float) -> list:
    return [0.0] * int(duration * SAMPLE_RATE)


def _write_wav(path: Path, samples: list) -> None:
    clamped = (max(-1.0, min(1.0, s)) for s in samples)
    frames = struct.pack("<" + "h" * len(samples), *(int(s * 32767) for s in clamped))
    with wave.open(str(path), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(frames)


def main():
    # Two-tone "incoming text" ding.
    new_round = _tone(660, 0.12) + _silence(0.02) + _tone(880, 0.16)
    _write_wav(OUT / "new_round.wav", new_round)

    # A single quick blip for a submitted reply.
    submit = _tone(1046, 0.12, volume=0.4)
    _write_wav(OUT / "submit.wav", submit)

    # 3-note ascending major chime (C5-E5-G5) for a round win.
    round_win = (
        _tone(523.25, 0.14) + _silence(0.02)
        + _tone(659.25, 0.14) + _silence(0.02)
        + _tone(783.99, 0.22, volume=0.5)
    )
    _write_wav(OUT / "round_win.wav", round_win)

    # Longer ascending arpeggio + sustained final note for winning the game.
    game_win = (
        _tone(523.25, 0.13) + _silence(0.015)
        + _tone(659.25, 0.13) + _silence(0.015)
        + _tone(783.99, 0.13, volume=0.5) + _silence(0.015)
        + _tone(1046.50, 0.5, volume=0.55)
    )
    _write_wav(OUT / "game_win.wav", game_win)

    print(f"Wrote 4 sound effects to {OUT}")


if __name__ == "__main__":
    main()
