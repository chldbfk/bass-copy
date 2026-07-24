"""
Phase 0 PoC 확장: librosa 비트 트래킹으로 템포(BPM)와 비트 타임스탬프를 추출하고,
이를 기준으로 노트 시퀀스를 마디/박자에 맞춰 정렬(quantize)한다.
4/4 박자를 가정(대부분의 대중음악 기본값)하고, 각 노트 길이를 표준 음표 단위
(온음표/2분음표/4분음표/8분음표/16분음표)로 근사한다.
"""
import sys
import librosa
import numpy as np

from poc_tab_render import parse_notes, filter_scale_noise

# 표준 음표 길이를 "1비트(4분음표)" 대비 비율로 정의
# 32분음표(0.125)는 검출 노이즈로 과도하게 잘게 분류되는 경향이 있어 제외 —
# 최소 단위를 16분음표로 두어(하한 clamp) 가독성을 확보한다.
NOTE_VALUES = [
    (4.0, "온음표"), (2.0, "2분음표"), (1.5, "점4분음표"),
    (1.0, "4분음표"), (0.75, "점8분음표"), (0.5, "8분음표"),
    (0.375, "점16분음표"), (0.25, "16분음표"),
]


def detect_tempo_and_beats(audio_path):
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    tempo = float(np.asarray(tempo).item()) if hasattr(tempo, "item") else float(tempo)
    return tempo, beat_times


def nearest_note_value(beats):
    best = min(NOTE_VALUES, key=lambda nv: abs(nv[0] - beats))
    return best[1]


def quantize_notes(notes, tempo, beat_times, beats_per_measure=4):
    beat_len = 60.0 / tempo
    # 첫 비트를 마디 1의 1박으로 삼음(가장 단순한 가정)
    first_beat = beat_times[0] if len(beat_times) > 0 else 0.0

    quantized = []
    for n in notes:
        beat_pos = (n["start"] - first_beat) / beat_len
        measure = int(beat_pos // beats_per_measure) + 1
        beat_in_measure = beat_pos % beats_per_measure

        dur_in_beats = n["dur"] / beat_len if "dur" in n else (n["end"] - n["start"]) / beat_len
        note_value = nearest_note_value(dur_in_beats)

        quantized.append({
            **n,
            "measure": measure,
            "beat_in_measure": round(beat_in_measure, 2),
            "beat_dur": dur_in_beats,
            "note_value": note_value,
        })
    return quantized


MIN_REST_BEATS = 0.2  # 이보다 짧은 빈 구간은 반올림 오차로 보고 쉼표로 표시하지 않음


def insert_rests(measure_notes, beats_per_measure=4):
    """한 마디 안에서 노트 사이 빈 구간을 찾아 쉼표 항목으로 채운다."""
    events = []
    cursor = 0.0
    for n in sorted(measure_notes, key=lambda x: x["beat_in_measure"]):
        gap = n["beat_in_measure"] - cursor
        if gap >= MIN_REST_BEATS:
            events.append({"type": "rest", "beat_in_measure": round(cursor, 2), "note_value": nearest_note_value(gap)})
        events.append({"type": "note", **n})
        cursor = max(cursor, n["beat_in_measure"] + n["beat_dur"])
    tail = beats_per_measure - cursor
    if tail >= MIN_REST_BEATS:
        events.append({"type": "rest", "beat_in_measure": round(cursor, 2), "note_value": nearest_note_value(tail)})
    return events


def main():
    audio_path = sys.argv[1] if len(sys.argv) > 1 else "일당백-데카당_mixed.mp3"
    notes_path = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"

    print(f"[1/2] 템포/비트 추정 중: {audio_path}")
    tempo, beat_times = detect_tempo_and_beats(audio_path)
    print(f"추정 템포: {tempo:.1f} BPM, 감지된 비트 수: {len(beat_times)}")

    notes = parse_notes(notes_path)
    notes = filter_scale_noise(notes)

    quantized = quantize_notes(notes, tempo, beat_times)

    print(f"\n=== 마디/박자 정렬 결과 (총 {len(quantized)}개 노트) ===")
    for n in quantized[:30]:
        print(f"  마디{n['measure']:>3} {n['beat_in_measure']:>4.2f}박  "
              f"{n['start']:6.2f}s  {n['name']:>4}  {n['note_value']}")
    if len(quantized) > 30:
        print(f"  ... (총 {len(quantized)}개 중 30개만 표시)")


if __name__ == "__main__":
    main()
