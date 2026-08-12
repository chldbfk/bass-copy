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

# 단순한 리프(피치 검출 잡음으로 실제보다 잘게 쪼개져 보이는 곡)를 위한 축소 어휘 —
# 4분/8분음표·쉼표만 쓴다. quantize_notes/insert_rests에 note_value_candidates로 넘기면 됨.
SIMPLE_NOTE_VALUES = [(1.0, "4분음표"), (0.5, "8분음표")]


def detect_tempo_and_beats(audio_path):
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    tempo = float(np.asarray(tempo).item()) if hasattr(tempo, "item") else float(tempo)
    return tempo, beat_times


def nearest_note_value(beats, candidates=NOTE_VALUES):
    best = min(candidates, key=lambda nv: abs(nv[0] - beats))
    return best[1]


def snap_notes_to_grid(notes, tempo, beat_times, grid_beats=0.5, max_note_beats=1.0):
    """피치 검출의 프레임 단위 흔들림(비브라토 등) 때문에 원래는 하나인 음이 여러 개의
    짧은 조각(16분음표/점16분음표)으로 쪼개져 나오는 경우가 있음. 실제 리프가 4분/8분음표
    단위로만 움직인다는 게 확인되면, 노트 시작 시각을 grid_beats(기본 8분음표=0.5박) 격자에
    스냅하고, 같은 칸에 몰린 조각들은 (원래 길이가 가장 긴, 즉 가장 확실한) 하나만 남긴다.
    노트 길이는 무조건 다음 노트까지 간격을 채우는 게 아니라, 그 음이 실제로 얼마나
    길게 소리났는지(원래 dur)를 격자에 스냅해서 우선 쓴다 — 짧게 끊기고 뒤에 진짜
    침묵(쉼표)이 있어야 하는 음까지 억지로 늘어나는 걸 막기 위함. 다음 노트와 겹치지
    않도록, 그리고 max_note_beats(기본 1박=4분음표)를 넘지 않도록 상한만 건다."""
    beat_len = 60.0 / tempo
    first_beat = beat_times[0] if len(beat_times) > 0 else 0.0

    slots = {}
    for n in notes:
        beat_pos = (n["start"] - first_beat) / beat_len
        snapped = round(beat_pos / grid_beats) * grid_beats
        existing = slots.get(snapped)
        if existing is None or n["dur"] > existing["dur"]:
            slots[snapped] = n

    snapped_beats = sorted(slots.keys())
    result = []
    for i, sb in enumerate(snapped_beats):
        n = slots[sb]
        dur_beats = round((n["dur"] / beat_len) / grid_beats) * grid_beats or grid_beats
        if i + 1 < len(snapped_beats):
            dur_beats = min(dur_beats, snapped_beats[i + 1] - sb)
        dur_beats = min(max_note_beats, dur_beats) or grid_beats
        start = first_beat + sb * beat_len
        dur = dur_beats * beat_len
        result.append({**n, "start": start, "end": start + dur, "dur": dur})
    return result


def quantize_notes(notes, tempo, beat_times, beats_per_measure=4, note_value_candidates=NOTE_VALUES):
    beat_len = 60.0 / tempo
    # 첫 비트를 마디 1의 1박으로 삼음(가장 단순한 가정)
    first_beat = beat_times[0] if len(beat_times) > 0 else 0.0

    quantized = []
    for n in notes:
        beat_pos = (n["start"] - first_beat) / beat_len
        measure = int(beat_pos // beats_per_measure) + 1
        beat_in_measure = beat_pos % beats_per_measure

        dur_in_beats = n["dur"] / beat_len if "dur" in n else (n["end"] - n["start"]) / beat_len
        note_value = nearest_note_value(dur_in_beats, note_value_candidates)

        quantized.append({
            **n,
            "measure": measure,
            "beat_in_measure": round(beat_in_measure, 2),
            "beat_dur": dur_in_beats,
            "note_value": note_value,
        })
    return quantized


MIN_REST_BEATS = 0.2  # 이보다 짧은 빈 구간은 반올림 오차로 보고 쉼표로 표시하지 않음


def _decompose_rest(gap, candidates):
    """gap(박)을 candidates 중 가장 큰 것부터 동전 거스름돈 주듯 채워, 각 조각을
    (박수, 이름) 리스트로 반환한다. candidates가 기본 어휘(NOTE_VALUES)일 땐 기존처럼
    통짜 하나로 근사(단일 후보만 반환)해 동작을 그대로 유지한다."""
    if candidates is NOTE_VALUES:
        return [(gap, nearest_note_value(gap, candidates))]
    remaining = gap
    pieces = []
    sorted_candidates = sorted(candidates, key=lambda nv: -nv[0])
    for beats, name in sorted_candidates:
        while remaining >= beats - 1e-6:
            pieces.append((beats, name))
            remaining -= beats
    if remaining >= MIN_REST_BEATS:
        pieces.append((remaining, nearest_note_value(remaining, candidates)))
    return pieces or [(gap, nearest_note_value(gap, candidates))]


def insert_rests(measure_notes, beats_per_measure=4, note_value_candidates=NOTE_VALUES):
    """한 마디 안에서 노트 사이 빈 구간을 찾아 쉼표 항목으로 채운다."""
    events = []
    cursor = 0.0
    for n in sorted(measure_notes, key=lambda x: x["beat_in_measure"]):
        gap = n["beat_in_measure"] - cursor
        if gap >= MIN_REST_BEATS:
            for beats, name in _decompose_rest(gap, note_value_candidates):
                events.append({"type": "rest", "beat_in_measure": round(cursor, 2), "note_value": name})
                cursor += beats
        events.append({"type": "note", **n})
        cursor = max(cursor, n["beat_in_measure"] + n["beat_dur"])
    tail = beats_per_measure - cursor
    if tail >= MIN_REST_BEATS:
        for beats, name in _decompose_rest(tail, note_value_candidates):
            events.append({"type": "rest", "beat_in_measure": round(cursor, 2), "note_value": name})
            cursor += beats
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
