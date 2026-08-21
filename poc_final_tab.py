"""
Phase 0 PoC 통합: 스케일 기반 노이즈 필터링 -> 박자/마디 정렬 -> 포지션 앵커 기반
운지 최적화 -> 마디선이 있는 최종 TAB 렌더링까지 전체 파이프라인을 하나로 묶는다.
"""
import sys

from poc_tab_render import parse_notes, filter_scale_noise, resolve_fingering, STRINGS
from poc_rhythm_quantize import (
    detect_tempo_and_beats, quantize_notes, insert_rests, NOTE_VALUES, SIMPLE_NOTE_VALUES, nearest_note_value,
)
from poc_chord_detect import detect_chords, chord_display_name

BEATS_PER_MEASURE = 4
NAME_TO_BEATS = {name: beats for beats, name in NOTE_VALUES}


def _close_measure_labels(events, rest_candidates):
    """insert_rests가 채우는 실제 커서 계산(박자 길이)은 항상 정확한데, 표시용 라벨은
    각 조각을 독립적으로 가장 가까운 이름에 반올림하다 보니(특히 SIMPLE 어휘에 없는
    자투리 값) 라벨끼리 더하면 4박을 넘거나 모자라 보이는 경우가 있었음
    (예: 마디4에서 실제 0.24박짜리 쉼표가 "8분음표(0.5박)"로 표시돼 라벨 합계가 4.5박이
    되어버림 — 사용자가 직접 세어보고 지적함, 2026-08-12). 여기서 라벨이 나타내는 박자를
    역산해 grid 단위로 반올림하고, 오차를 마지막 항목에 몰아 라벨 합계가 항상 정확히
    BEATS_PER_MEASURE가 되도록 보정한다. (내부 타이밍/MusicXML은 원래도 정확했으므로
    건드리지 않고, 사람이 읽는 라벨 표기만 고친다.)"""
    grid = min(beats for beats, _ in rest_candidates)

    def label_of(e):
        return e["value"].replace("(슬라이드)", "") if e["type"] == "note" else e["note_value"]

    rounded = [round(NAME_TO_BEATS.get(label_of(e), grid) / grid) * grid or grid for e in events]
    diff = round(BEATS_PER_MEASURE - sum(rounded), 6)
    if events and diff != 0:
        adjusted = rounded[-1] + diff
        if adjusted < grid:  # 마지막 항목이 grid 밑으로 내려가면 그 앞 항목에 넘겨서 흡수
            rounded[-2] = max(grid, rounded[-2] + adjusted - grid) if len(rounded) > 1 else rounded[-2]
            adjusted = grid
        rounded[-1] = adjusted

    for e, beats in zip(events, rounded):
        new_label = nearest_note_value(beats, NOTE_VALUES)
        if e["type"] == "rest":
            e["note_value"] = new_label
        else:
            suffix = "(슬라이드)" if "(슬라이드)" in e["value"] else ""
            e["value"] = new_label + suffix


def build_display_units(notes, groups):
    """슬라이드 그룹(크로매틱 런 + 옥타브 슬라이드, (시작idx, 끝idx) 범위)을 반영해
    ASCII TAB에서 한 칸으로 그릴 렌더링 단위 목록을 만든다.
    슬라이드가 아닌 노트는 (i, i)로, 슬라이드는 (i, j)로 표시해 한 칸에 "시작프렛/끝프렛"으로 압축한다."""
    group_end = {i: j for i, j in groups}
    units = []
    k, n = 0, len(notes)
    while k < n:
        if k in group_end:
            j = group_end[k]
            units.append((k, j))
            k = j + 1
        else:
            units.append((k, k))
            k += 1
    return units


def render_tab_by_measure(notes, path, quantized, groups=(), chords=None):
    """4/4 기준으로 각 마디가 실제로 4박을 다 채우도록, 연주된 노트 사이 빈 구간은
    쉼표 칸으로 명시해서 그린다 — 예전엔 연주된 노트만 나열해서(쉼표 미표시) 마디 합계가
    4박에 못 미치는 것처럼 보였음(사용자 지적으로 발견, 2026-08-12). MusicXML(build_musicxml)은
    처음부터 insert_rests()로 쉼표를 채워왔으니 여기서도 같은 함수를 재사용한다."""
    units = build_display_units(notes, groups)
    chords = chords or {}

    # 렌더링 단위(슬라이드 그룹 포함) -> 마디별 노트 목록. 슬라이드 그룹은 시작~끝을 합친
    # 하나의 박자 길이(beat_dur)로 묶어서 insert_rests가 그룹 전체를 하나의 이벤트로 보게 한다.
    measure_notes = {}
    for i, j in units:
        s_idx, fret_start = path[i]
        _, fret_end = path[j]
        cell = f"{fret_start}/{fret_end}" if j > i else str(fret_start)
        q_start, q_end = quantized[i], quantized[j]
        value = q_start["note_value"] if j == i else f"{q_start['note_value']}(슬라이드)"
        beat_dur = (q_end["beat_in_measure"] + q_end["beat_dur"]) - q_start["beat_in_measure"] if j > i else q_start["beat_dur"]
        measure_notes.setdefault(q_start["measure"], []).append({
            "string": s_idx, "cell": cell, "value": value,
            "start": q_start["start"], "end": q_end["end"],
            "beat_in_measure": q_start["beat_in_measure"], "beat_dur": beat_dur,
        })

    # 쉼표를 몇 분음표 단위로 쪼갤지도 실제 곡의 세분화 수준(quantize_notes가 고른 어휘)을
    # 그대로 따른다 — 노트는 4분/8분음표만 쓰는데 쉼표만 16분음표로 잘게 나오면 안 되니까.
    used_labels = {q["note_value"].replace("(슬라이드)", "") for q in quantized}
    simple_labels = {label for _, label in SIMPLE_NOTE_VALUES}
    rest_candidates = SIMPLE_NOTE_VALUES if used_labels <= simple_labels else NOTE_VALUES

    out = []
    for m in sorted(measure_notes.keys()):
        events = insert_rests(measure_notes[m], beats_per_measure=BEATS_PER_MEASURE,
                               note_value_candidates=rest_candidates)
        _close_measure_labels(events, rest_candidates)
        note_events = [e for e in events if e["type"] == "note"]
        chord_label = f"  코드: {chord_display_name(*chords[m])}" if m in chords else ""
        start_s = note_events[0]["start"] if note_events else float(m - 1) * BEATS_PER_MEASURE
        end_s = note_events[-1]["end"] if note_events else start_s
        out.append(f"[마디 {m}] ({start_s:.1f}s ~ {end_s:.1f}s){chord_label}")

        cells, values = [], []
        for e in events:
            if e["type"] == "rest":
                cells.append(None)
                values.append(e["note_value"].replace("음표", "쉼표"))
            else:
                cells.append((e["string"], e["cell"]))
                values.append(e["value"])
        widths = [max(len(c[1]), 2) if c else 2 for c in cells]
        for si, (label, _) in enumerate(STRINGS):
            row = [c[1].rjust(w) if c and c[0] == si else "-" * w for c, w in zip(cells, widths)]
            out.append(f"{label}|-" + "-".join(row) + "-|")
        out.append(f"   음표: {' '.join(values)}")
        out.append("")
    return "\n".join(out)


def main():
    audio_path = sys.argv[1] if len(sys.argv) > 1 else "일당백-데카당_mixed.mp3"
    notes_path = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "poc_final_tab_output.txt"
    chord_audio_path = sys.argv[4] if len(sys.argv) > 4 else None
    apply_chromatic_slides = sys.argv[5].lower() not in ("0", "false") if len(sys.argv) > 5 else True

    print(f"[1/4] 노트 파싱: {notes_path}")
    notes = parse_notes(notes_path)

    print("[2/4] 스케일 기반 노이즈 필터링")
    notes = filter_scale_noise(notes)

    print(f"[3/4] 템포/비트 감지: {audio_path}")
    tempo, beat_times = detect_tempo_and_beats(audio_path)
    print(f"  추정 템포: {tempo:.1f} BPM")
    quantized = quantize_notes(notes, tempo, beat_times)

    print("[4/4] 운지 최적화 및 렌더링")
    path, groups = resolve_fingering(notes, apply_chromatic_slides=apply_chromatic_slides)
    chords = detect_chords(chord_audio_path, tempo, beat_times) if chord_audio_path else {}

    tab_text = render_tab_by_measure(notes, path, quantized, groups=groups, chords=chords)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"총 {len(notes)}개 노트, 추정 템포 {tempo:.1f} BPM, 표준 4현 베이스 튜닝(E1-A1-D2-G2) 기준\n")
        if groups:
            f.write(f"검출된 슬라이드 {len(groups)}건 (같은 줄 프렛으로 강제, 이후 노트도 새 위치 기준 재최적화):\n")
            for i, j in groups:
                names = " -> ".join(f"{notes[k]['name']}(프렛{path[k][1]})" for k in range(i, j + 1))
                f.write(f"  {notes[i]['start']:.2f}s~{notes[j]['end']:.2f}s  {names}\n")
        f.write("\n")
        f.write(tab_text)

    print(f"최종 TAB 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
