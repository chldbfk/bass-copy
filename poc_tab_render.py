"""
Phase 0 PoC: poc_output.txt의 노트 시퀀스(음이름+옥타브)를
4현 베이스 표준 튜닝(E1-A1-D2-G2) 기준 TAB으로 변환한다.
계획서 4-1 섹션에서 설계한 비용 함수(프렛 이동 거리 + 줄 변경 페널티 + 오픈 스트링 선호)를
동적계획법(DP)으로 풀어 운지를 결정한다.
"""
import re
import sys

from poc_scale_analysis import estimate_key, MAJOR_SCALE_STEPS, MINOR_SCALE_STEPS, PITCH_CLASS_NAMES

NOISE_MAX_DURATION = 0.15  # 이 시간보다 짧고 스케일 밖인 노트는 검출 노이즈로 간주해 제거

NOTE_TO_SEMITONE = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
# 표시 순서: 화면 위쪽이 높은 줄(G), 아래쪽이 낮은 줄(E) — 실제 TAB 표기 관례
STRINGS = [("G", 43), ("D", 38), ("A", 33), ("E", 28)]
MAX_FRET = 20

# 실제 베이스 운지는 "같은 줄을 유지하는 것"이 아니라 "손 위치(포지션)를 유지하는 것"이 핵심.
# 4손가락으로 4개 프렛 범위(포지션 박스)를 짚고, 그 안에서는 줄을 自由롭게 넘나들어도
# 손 이동이 전혀 없음 — 같은 음이 다른 줄에도 있을 수 있으므로 포지션 안에서 줄을 바꾸는 건 사실상 공짜.
# 포지션 박스(보통 4프렛)를 벗어날 때만 실제 손 이동(포지션 시프트) 비용이 발생.
POSITION_SPAN = 3          # 포지션 박스 안으로 인정하는 프렛 거리(0~3프렛 이내)
WITHIN_POSITION_COST = 0.1  # 포지션 박스 안 이동 비용(사실상 손가락만 바꾸면 됨)
SHIFT_COST_PER_FRET = 1.0   # 포지션 박스를 벗어난 뒤 추가 프렛당 비용(실제 손 이동)
STRING_CHANGE_PENALTY = 0.2  # 포지션이 같다면 줄 변경 자체는 거의 공짜에 가까움(동점 방지용 미세 가중치)
OPEN_STRING_BONUS = 1.0

# 스케일 반영 2차 최적화: 특정 음이 스케일에 속하는지 여부는 (같은 음이라면) 어느 줄/프렛을
# 고르든 동일하므로 프렛 선택 자체에 영향을 주지 않는다. 대신 스케일 노트로 걸러진(노이즈 제거된)
# 안정적인 시퀀스를 바탕으로, 국소 구간에서 하나의 포지션 박스에 더 오래 머물도록 유도한다
# (실제 연주자가 스케일 박스 하나를 잡고 쭉 이어가는 것과 같은 효과).
ANCHOR_WINDOW = 3    # 앞뒤 몇 개 노트를 봐서 '대표 포지션'을 정할지
ANCHOR_WEIGHT = 0.4  # 대표 포지션에서 벗어날 때 추가되는 비용 가중치

NOTE_PATTERN = re.compile(
    r"([\d.]+)s\s*~\s*([\d.]+)s\s*\(([\d.]+)s\)\s+([A-G]#?-?\d+)"
)


def note_name_to_midi(name):
    m = re.match(r"([A-G]#?)(-?\d+)", name)
    letter, octave = m.group(1), int(m.group(2))
    return 12 * (octave + 1) + NOTE_TO_SEMITONE[letter]


def parse_notes(path):
    notes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = NOTE_PATTERN.search(line)
            if m:
                start, end, dur, name = m.groups()
                midi = note_name_to_midi(name)
                notes.append({
                    "start": float(start),
                    "end": float(end),
                    "dur": float(dur),
                    "name": name,
                    "midi": midi,
                    "pc": midi % 12,
                })
    return notes


# 반음씩 연속으로(크로매틱) 상승/하강하는 3개 이상의 짧은 노트는 검출 노이즈가 아니라
# 한 줄 위에서 슬라이드/해머링-풀오프로 이어치는 런(passing run)인 경우가 많다.
# 스케일 밖 음(예: A장조 스케일에 없는 A natural)이라도 이런 런의 일부라면 노이즈 필터에서 보호한다.
CHROMATIC_RUN_MAX_GAP = 0.15
CHROMATIC_RUN_MIN_LEN = 3


def find_chromatic_runs(notes, max_gap=CHROMATIC_RUN_MAX_GAP, min_len=CHROMATIC_RUN_MIN_LEN):
    """반음씩 같은 방향으로 연속되는 노트 구간들을 (시작 인덱스, 끝 인덱스) 범위로 반환한다."""
    runs = []
    n = len(notes)
    i = 0
    while i < n - 1:
        j = i
        direction = None
        while j + 1 < n:
            step = notes[j + 1]["midi"] - notes[j]["midi"]
            gap = notes[j + 1]["start"] - notes[j]["end"]
            if abs(step) == 1 and gap <= max_gap and (direction is None or step == direction):
                direction = step
                j += 1
            else:
                break
        if j - i + 1 >= min_len:
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def filter_scale_noise(notes):
    (corr, tonic, mode), _ = estimate_key(notes)
    scale_steps = MAJOR_SCALE_STEPS if mode == "major" else MINOR_SCALE_STEPS
    scale_pcs = {(tonic + s) % 12 for s in scale_steps}

    print(f"추정 조성: {PITCH_CLASS_NAMES[tonic]} {mode} (상관계수 {corr:.3f})")

    protected = set()
    for i, j in find_chromatic_runs(notes):
        protected.update(range(i, j + 1))

    cleaned = []
    removed = 0
    for idx, n in enumerate(notes):
        if idx not in protected and n["pc"] not in scale_pcs and n["dur"] < NOISE_MAX_DURATION:
            removed += 1
            continue
        cleaned.append(n)
    print(f"스케일 밖 + {NOISE_MAX_DURATION}s 미만 노이즈 후보 {removed}개 제거 "
          f"(크로매틱 런으로 보호된 {len(protected)}개 제외, 총 {len(notes)} -> {len(cleaned)})")
    return cleaned


def candidates(midi):
    result = []
    for idx, (_, open_midi) in enumerate(STRINGS):
        fret = midi - open_midi
        if 0 <= fret <= MAX_FRET:
            result.append((idx, fret))
    if not result:
        # 베이스 음역을 벗어나면 가장 가까운 줄에서 클리핑(예외 처리)
        best_idx = min(range(4), key=lambda i: abs(midi - STRINGS[i][1]))
        fret = max(0, min(MAX_FRET, midi - STRINGS[best_idx][1]))
        result.append((best_idx, fret))
    return result


def transition_cost(prev, curr):
    if prev is None:
        return 0.0
    ps, pf = prev
    cs, cf = curr

    d = abs(cf - pf)
    if d <= POSITION_SPAN:
        c = d * WITHIN_POSITION_COST
    else:
        c = POSITION_SPAN * WITHIN_POSITION_COST + (d - POSITION_SPAN) * SHIFT_COST_PER_FRET

    if cs != ps:
        c += STRING_CHANGE_PENALTY
    if cf == 0:
        c -= OPEN_STRING_BONUS
    return c


def run_dp(notes, anchors=None, pinned=None):
    """anchors가 주어지면 각 노트마다 '주변 구간의 대표 프렛(앵커)'에서
    멀어질수록 추가 비용을 매겨, 국소적으로 안정된 포지션 박스를 유지하도록 유도한다.
    pinned={idx: (string,fret)}이 주어지면 그 인덱스는 다른 후보를 고려하지 않고
    무조건 그 값으로 고정한 채 나머지 노트만 재최적화한다(슬라이드로 이미 확정된
    노트를 그대로 두고, 그 앞뒤 노트들이 새 위치에 맞춰 자연스럽게 이어지도록 하기 위함)."""
    prev_layer = {None: (0.0, None)}
    layers = []
    for i, note in enumerate(notes):
        anchor_cost = 0.0
        layer = {}
        cand_list = [pinned[i]] if pinned and i in pinned else candidates(note["midi"])
        for c in cand_list:
            cs, cf = c
            if anchors is not None:
                anchor_cost = abs(cf - anchors[i]) * ANCHOR_WEIGHT
            best_cost, best_prev = min(
                ((pcost + transition_cost(pc, c) + anchor_cost, pc) for pc, (pcost, _) in prev_layer.items()),
                key=lambda x: x[0],
            )
            layer[c] = (best_cost, best_prev)
        layers.append(layer)
        prev_layer = layer

    last_layer = layers[-1]
    best = min(last_layer, key=lambda k: last_layer[k][0])
    path = [best]
    for i in range(len(layers) - 1, 0, -1):
        best = layers[i][best][1]
        path.append(best)
    path.reverse()
    return path


def local_fret_anchors(path, window=3):
    """각 노트 위치마다 주변(앞뒤 window개) 구간에서 실제 선택된 프렛의 중앙값을 계산.
    이 값이 '지금 손이 자리 잡고 있어야 할 포지션'의 기준점 역할을 한다."""
    n = len(path)
    anchors = []
    for i in range(n):
        lo, hi = max(0, i - window), min(n, i + window + 1)
        frets = sorted(f for _, f in path[lo:hi])
        anchors.append(frets[len(frets) // 2])
    return anchors


def optimize_fingering(notes):
    # 1차: 순수 인접-노트 기반 DP로 기준 경로 산출
    baseline_path = run_dp(notes)
    # 2차: 기준 경로에서 국소 앵커(주변 구간 대표 포지션)를 뽑아,
    #      스케일 박스 안에 더 오래 머무르도록 재최적화
    anchors = local_fret_anchors(baseline_path, window=ANCHOR_WINDOW)
    return run_dp(notes, anchors=anchors)


# 정확히 1옥타브(12반음) 차이 나는 같은 음이름이 이 간격 이내로 붙어 있으면
# 서로 다른 음을 짚은 게 아니라 같은 줄에서 위/아래로 짚는 슬라이드 주법으로 간주한다.
OCTAVE_SLIDE_MAX_GAP = 0.6


def detect_octave_slides(notes, max_gap=OCTAVE_SLIDE_MAX_GAP):
    """인접한 두 노트가 정확히 1옥타브 차이(같은 피치클래스)이고 간격이 짧으면
    슬라이드로 판정해 {시작 인덱스: 반음차(+-12)} 딕셔너리를 반환한다."""
    slides = {}
    for i in range(len(notes) - 1):
        a, b = notes[i], notes[i + 1]
        if abs(b["midi"] - a["midi"]) == 12 and (b["start"] - a["end"]) <= max_gap:
            slides[i] = b["midi"] - a["midi"]
    return slides


def apply_octave_slides(notes, path, slides):
    """슬라이드로 판정된 두 노트는 반드시 같은 줄 위에서 12프렛 이동으로 이어져야 한다.
    두 노트 각각의 미디 노트 번호가 고정돼 있으므로, 줄을 정하면 두 프렛 값이 자동으로
    정해진다(fret2 = fret1 + 반음차). 두 프렛이 모두 0~MAX_FRET 안에 들어오는 줄만
    유효하며(예: 옥타브 아래로 내려가는 슬라이드는 낮은 줄에서만 가능), 그런 줄이 없으면
    (물리적으로 슬라이드가 불가능한 조합) 원래 DP 결과를 그대로 둔다."""
    path = list(path)
    for i, delta in slides.items():
        valid = []
        for s_idx, (_, open_midi) in enumerate(STRINGS):
            f1 = notes[i]["midi"] - open_midi
            f2 = f1 + delta
            if 0 <= f1 <= MAX_FRET and 0 <= f2 <= MAX_FRET:
                valid.append((s_idx, f1, f2))
        if not valid:
            continue
        cur_s1, cur_s2 = path[i][0], path[i + 1][0]
        chosen = next((v for v in valid if v[0] == cur_s1), None) \
            or next((v for v in valid if v[0] == cur_s2), None) \
            or min(valid, key=lambda v: v[1])  # 여러 줄이 가능하면 가장 낮은 프렛(편한 자리) 우선
        s_idx, f1, f2 = chosen
        path[i] = (s_idx, f1)
        path[i + 1] = (s_idx, f2)
    return path


def apply_chromatic_run_slides(notes, path, runs):
    """find_chromatic_runs()가 찾은 각 런(연속 반음 진행 구간)을 한 줄 위에서
    연속된 프렛으로 강제한다 — 실제 연주에서는 줄을 오가며 낱개로 짚는 게 아니라
    한 줄에서 슬라이드/해머링으로 쭉 이어치는 경우가 대부분이기 때문."""
    path = list(path)
    for i, j in runs:
        valid = []
        for s_idx, (_, open_midi) in enumerate(STRINGS):
            frets = [notes[k]["midi"] - open_midi for k in range(i, j + 1)]
            if all(0 <= f <= MAX_FRET for f in frets):
                valid.append((s_idx, frets))
        if not valid:
            continue
        cur_s = path[i][0]
        chosen = next((v for v in valid if v[0] == cur_s), None) or min(valid, key=lambda v: v[1][0])
        s_idx, frets = chosen
        for k, f in zip(range(i, j + 1), frets):
            path[k] = (s_idx, f)
    return path


# color_mixed 작업 중 사용자가 직접 확인해준 패턴: 반복되는 G1이 A#1로 3반음 뛰는 구간도
# (사이에 크로매틱 경유음이 잡히지 않았더라도) 실제로는 슬라이드였음. 반면 같은 곡의
# A#1->G#1(하행 2반음, 비슷한 간격)은 슬라이드가 아니었음 — 즉 "간격+반음차가 작다"는
# 조건만으로는 두 경우를 구별할 수 없어(이 곡에서 실제로 오탐남), 지금은 사용자가 검증해준
# (출발음, 도착음) 조합만 좁게 매칭한다. 더 일반적인 규칙(예: 원본 프레임 단위 피치 곡선에서
# 실제 연속 글리산도 여부 확인)은 다른 곡 예시로 더 검증한 뒤 넓힐 것.
VALIDATED_LEAP_SLIDES = [(31, 34)]  # (출발 MIDI, 도착 MIDI) — G1 -> A#1
LEAP_SLIDE_MAX_GAP = 0.3


def detect_leap_slides(notes, pairs=VALIDATED_LEAP_SLIDES, max_gap=LEAP_SLIDE_MAX_GAP):
    slides = {}
    for i in range(len(notes) - 1):
        a, b = notes[i], notes[i + 1]
        if (a["midi"], b["midi"]) in pairs and (b["start"] - a["end"]) <= max_gap:
            slides[i] = b["midi"] - a["midi"]
    return slides


def propagate_slide_landing(notes, path, slide_ends):
    """슬라이드가 도착한 (줄,프렛) 바로 다음에 '같은 음이 반복되는 구간'이 있으면,
    그 구간 전체를 도착 프렛과 가장 가까운 (포지션 박스 안의) 위치로 이어붙인다.

    앵커(local_fret_anchors)의 대칭 윈도우 중앙값 방식으로 이 문제를 풀려고 했으나,
    슬라이드 직후 노트들의 윈도우는 '아직 재조정되지 않은 다수의 예전 프렛'에 표가 쏠려서
    슬라이드로 만든 새 위치가 묻혀버리는 문제가 있었음(실사용자 피드백으로 발견). 그래서
    이렇게 명시적으로: 같은 음이 반복되는 동안만 도착 위치를 이어받고, 음이 바뀌는 순간
    (다음 프레이즈로 넘어가는 지점)엔 자동으로 멈춰서 원래 최적화 결과를 그대로 둔다 —
    실제로 다음 프레이즈까지 억지로 같은 포지션에 묶어두면 오히려 부자연스러웠음."""
    path = list(path)
    n = len(notes)
    for end_idx in slide_ends:
        land_s, land_f = path[end_idx]
        k = end_idx + 1
        if k >= n:
            continue
        repeat_midi = notes[k]["midi"]
        j = k
        while j + 1 < n and notes[j + 1]["midi"] == repeat_midi and (notes[j + 1]["start"] - notes[j]["end"]) <= 1.0:
            j += 1
        if j < k:
            continue
        best = None
        for s_idx, (_, open_midi) in enumerate(STRINGS):
            f = repeat_midi - open_midi
            if 0 <= f <= MAX_FRET:
                dist = abs(f - land_f)
                if best is None or dist < best[0]:
                    best = (dist, s_idx, f)
        if best and best[0] <= POSITION_SPAN:
            _, s_idx, f = best
            for idx in range(k, j + 1):
                path[idx] = (s_idx, f)
    return path


def resolve_fingering(notes):
    """전체 운지 파이프라인. 크로매틱 런/옥타브 슬라이드/검증된 도약 슬라이드를 강제 배치한 뒤,
    그 노트들은 고정(pinned)한 채 나머지 노트의 앵커를 새 위치 기준으로 다시 계산해 재최적화한다.

    이 마지막 재최적화 단계가 없으면, 슬라이드로 강제 이동된 노트 '바로 다음' 노트들이
    슬라이드 적용 전(前) 위치를 기준으로 계산된 낡은 앵커를 그대로 따라가 버려서, 슬라이드
    직후에도 여전히 예전의 낮은 프렛(예: D현 1프렛)으로 튀는 부자연스러운 결과가 나왔음
    (실사용자 피드백으로 발견 — 슬라이드로 도착한 위치를 유지한 채 인접 줄의 같은 프렛을
    쓰는 게 실제로 훨씬 편한 운지였음)."""
    baseline_path = run_dp(notes)
    anchors1 = local_fret_anchors(baseline_path, window=ANCHOR_WINDOW)
    path = run_dp(notes, anchors=anchors1)

    runs = find_chromatic_runs(notes)
    path = apply_chromatic_run_slides(notes, path, runs)
    octave_slides = detect_octave_slides(notes)
    path = apply_octave_slides(notes, path, octave_slides)
    leap_slides = detect_leap_slides(notes)
    path = apply_octave_slides(notes, path, leap_slides)

    pinned = {}
    for i, j in runs:
        for k in range(i, j + 1):
            pinned[k] = path[k]
    for i in octave_slides:
        pinned[i], pinned[i + 1] = path[i], path[i + 1]
    for i in leap_slides:
        pinned[i], pinned[i + 1] = path[i], path[i + 1]

    anchors2 = local_fret_anchors(path, window=ANCHOR_WINDOW)
    final_path = run_dp(notes, anchors=anchors2, pinned=pinned)

    slide_groups = list(runs) + [(i, i + 1) for i in octave_slides] + [(i, i + 1) for i in leap_slides]
    slide_ends = [j for _, j in slide_groups]
    final_path = propagate_slide_landing(notes, final_path, slide_ends)

    return final_path, slide_groups


def render_ascii_tab(notes, path, per_line=16):
    out = []
    for chunk_start in range(0, len(notes), per_line):
        chunk_notes = notes[chunk_start:chunk_start + per_line]
        chunk_path = path[chunk_start:chunk_start + per_line]

        out.append(f"[{chunk_notes[0]['start']:.1f}s ~ {chunk_notes[-1]['end']:.1f}s]")
        for si, (label, _) in enumerate(STRINGS):
            cells = []
            for (s_idx, fret) in chunk_path:
                cells.append(f"{fret:>2}" if s_idx == si else "--")
            out.append(f"{label}|-" + "-".join(cells) + "-|")
        out.append("")
    return "\n".join(out)


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else "poc_output.txt"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "poc_tab_output.txt"

    notes = parse_notes(input_path)
    print(f"파싱된 노트 개수: {len(notes)}")

    notes = filter_scale_noise(notes)

    path = optimize_fingering(notes)

    tab_text = render_ascii_tab(notes, path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"총 {len(notes)}개 노트, 표준 4현 베이스 튜닝(E1-A1-D2-G2) 기준\n\n")
        f.write(tab_text)

    print(f"TAB 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
