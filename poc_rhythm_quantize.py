"""
Phase 0 PoC 확장: librosa 비트 트래킹으로 템포(BPM)와 비트 타임스탬프를 추출하고,
이를 기준으로 노트 시퀀스를 마디/박자에 맞춰 정렬(quantize)한다.
4/4 박자를 가정(대부분의 대중음악 기본값)하고, 각 노트 길이를 표준 음표 단위
(온음표/2분음표/4분음표/8분음표/16분음표)로 근사한다.
"""
import sys
import math
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


def infer_note_grid(notes, tempo):
    """SIMPLE_NOTE_VALUES(4분/8분만) vs NOTE_VALUES(16분까지) 중 이 곡에 맞는 어휘를
    사람이 곡 느낌을 보고 고르지 않고, 노트 시작 시각 간격(IOI)의 실제 분포로 자동 판단한다.
    IOI를 8분음표(0.5박) 격자에 스냅했을 때 평균 오차가 작으면 이미 8분음표 단위로 충분히
    설명된다는 뜻 -> SIMPLE 어휘로 충분(16분음표로 쪼갤 근거 없음, 대개 피치검출 잡음).
    오차가 크면 실제로 8분음표보다 촘촘한 움직임이 있다는 뜻 -> 기본 어휘(16분음표 포함) 사용.
    2026-08-12: Stand-By-Me 재생성 때 이 판단을 매번 곡마다 손으로 고르다가 사용자 지적으로
    자동화함(더 이상 곡별로 물어보지 않음) — 재실행/새 곡 모두 이 함수가 대신 판단."""
    beat_len = 60.0 / tempo
    starts = sorted(n["start"] for n in notes)
    if len(starts) < 3:
        return SIMPLE_NOTE_VALUES
    iois = [(starts[i + 1] - starts[i]) / beat_len for i in range(len(starts) - 1)]
    iois = [x for x in iois if x > 0.05]  # 거의 동시(노이즈성 겹침)는 통계에서 제외
    if not iois:
        return SIMPLE_NOTE_VALUES
    grid = 0.5  # 8분음표 = 0.5박
    rel_err = sum(abs(x - round(x / grid) * grid) for x in iois) / len(iois) / grid
    return SIMPLE_NOTE_VALUES if rel_err < 0.2 else NOTE_VALUES


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


def quantize_notes(notes, tempo, beat_times, beats_per_measure=4, note_value_candidates=None):
    """note_value_candidates를 안 넘기면(기본값) infer_note_grid()가 노트 타이밍 데이터를 보고
    SIMPLE/기본 어휘 중 뭐가 맞는지 자동으로 고른다 — 곡마다 수동으로 고를 필요 없음."""
    if note_value_candidates is None:
        note_value_candidates = infer_note_grid(notes, tempo)
    beat_len = 60.0 / tempo
    # 첫 비트를 마디 1의 1박으로 삼음(가장 단순한 가정)
    first_beat = beat_times[0] if len(beat_times) > 0 else 0.0

    # 앵커(첫 비트 시점)가 실제 첫 노트보다 뒤에 있으면 그 노트가 beat_pos<0이 되어
    # "마디 0"(또는 음수 마디)이라는 비정상적인 번호로 밀려나고, 그 뒤 모든 마디 번호가
    # 하나씩 밀려 보임(AlphaTab 등 렌더러는 1번부터 정상적으로 세므로 텍스트 마디 번호와
    # 렌더된 악보의 마디 번호가 어긋나 버림 — 2026-08-12 Stand-By-Me에서 사용자가 렌더된
    # 악보 스크린샷으로 발견). BPM을 override했을 때 auto-detected 앵커가 실제 곡 시작보다
    # 뒤에 있는 경우가 흔하므로, 앵커를 마디(4박) 단위로 통째로 앞당겨서 모든 노트가
    # beat_pos>=0(마디 1부터)에 들어가도록 보정한다 — 박자 내 위상은 그대로 유지됨.
    if notes:
        earliest = min(n["start"] for n in notes)
        if first_beat > earliest:
            measure_len = beat_len * beats_per_measure
            steps = math.ceil((first_beat - earliest) / measure_len)
            first_beat -= steps * measure_len

    EPS = 1e-6  # 부동소수점 오차 보정용. 예: 마디 경계에 정확히 걸치는 노트가
    # (t - first_beat)/beat_len 계산 중 부동소수점 오차로 4.0 대신 3.999999999997처럼
    # 나오면 //로 나눌 때 이전 마디로 잘못 떨어짐(Stand-By-Me에서 실사용자가 "1마디가
    # 4.5박으로 넘친다"고 확인 — 실제로는 마디2 첫 음이 마디1로 잘못 들어간 표기 오류였음).
    quantized = []
    for n in notes:
        beat_pos = (n["start"] - first_beat) / beat_len
        measure = int((beat_pos + EPS) // beats_per_measure) + 1
        beat_in_measure = round((beat_pos + EPS) % beats_per_measure, 2)

        # EPS가 부동소수점 오차를 다 못 삼키는 경우가 있음(2026-08-21, 나는나비 마디4→5
        # 경계에서 실측: beat_pos가 16.0에서 1.01e-6만큼 모자란 15.999998986 — EPS(1e-6)를
        # 더해도 여전히 16.0 미만이라 // 나눗셈은 이전 마디(4)로 떨어지는데, 그 나머지값
        # 3.999999986을 소수점 2자리로 반올림하면 4.0이 되어버려서, 있을 수 없는 "마디4의
        # 4.0박"이라는 값이 생김 — 실제로는 마디5 1박(0.0)에 있어야 할 노트가 마디4에
        # 갇혀버리고, 그 자리를 insert_rests()가 마디5 맨 앞 가짜 쉼표로 채워서 마디5부터
        # 모든 노트가 반박자씩 밀려 보이는 결과가 나왔음. EPS 값을 계속 키워 맞추기보다,
        # 반올림 후 결과가 마디 길이에 도달/초과하면 그 자체를 다음 마디 0박으로 넘겨서
        # 근본적으로 막는다.
        if beat_in_measure >= beats_per_measure:
            measure += 1
            beat_in_measure = 0.0

        dur_in_beats = n["dur"] / beat_len if "dur" in n else (n["end"] - n["start"]) / beat_len
        note_value = nearest_note_value(dur_in_beats, note_value_candidates)

        quantized.append({
            **n,
            "measure": measure,
            "beat_in_measure": beat_in_measure,
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
