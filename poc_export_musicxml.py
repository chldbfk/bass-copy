"""
Phase 0 PoC: 파이프라인 결과(마디/박자 정렬 + 운지 최적화)를 MusicXML로 변환한다.
AlphaTab 같은 전문 렌더러에 넘기면 빔(beam) 연결, 스템 방향 등은 렌더러가
자동으로 계산해주므로, 여기서는 정확한 음정·박자·TAB(줄/프렛) 정보만 만든다.
"""
import sys
import xml.sax.saxutils as sx

from poc_tab_render import parse_notes, filter_scale_noise, resolve_fingering, STRINGS
from poc_rhythm_quantize import (
    detect_tempo_and_beats, quantize_notes, insert_rests, NOTE_VALUES, nearest_note_value,
    snap_notes_to_grid,
)
from poc_scale_analysis import estimate_key, MAJOR_SCALE_STEPS, MINOR_SCALE_STEPS, PITCH_CLASS_NAMES
from poc_chord_detect import detect_chords

# 코드 품질(poc_chord_detect의 quality 문자열) -> MusicXML <kind> 값/표시 텍스트
CHORD_KIND_BY_QUALITY = {
    "": ("major", ""),
    "m": ("minor", "m"),
    "7": ("dominant", "7"),
    "m7": ("minor-seventh", "m7"),
    "maj7": ("major-seventh", "maj7"),
}

DIVISIONS = 24  # 4분음표 = 24 -> 32분음표(3), 점8분음표(18) 등이 전부 정수로 떨어짐
BEATS_PER_MEASURE = 4

NOTE_VALUE_BEATS = {label: beats for beats, label in NOTE_VALUES}
NOTE_VALUE_TO_TYPE = {
    "온음표": ("whole", False), "2분음표": ("half", False),
    "점4분음표": ("quarter", True), "4분음표": ("quarter", False),
    "점8분음표": ("eighth", True), "8분음표": ("eighth", False),
    "점16분음표": ("16th", True), "16분음표": ("16th", False),
    "32분음표": ("32nd", False),
}
FLAGS_BY_TYPE = {"eighth": 1, "16th": 2, "32nd": 3}  # 빔으로 묶을 수 있는(꼬리 있는) 음표만


def compute_beams(events):
    """같은 박(beat) 안에서 연속된 '꼬리 있는' 음표(8분음표 이하)들을 빔으로 묶는다.
    쉼표나 박 경계를 만나면 그룹이 끊긴다. 반환값: events와 같은 길이의 리스트,
    각 원소는 [(레벨, 상태), ...] (예: [(1,"begin"),(2,"begin")])."""
    cum = 0.0
    beat_index = []
    for e in events:
        beat_index.append(int(cum + 1e-6))
        cum += NOTE_VALUE_BEATS[e["note_value"]]

    def flags_of(i):
        note_type = NOTE_VALUE_TO_TYPE.get(events[i]["note_value"], ("quarter", False))[0]
        return FLAGS_BY_TYPE.get(note_type, 0)

    beams = [[] for _ in events]
    i, n = 0, len(events)
    while i < n:
        if events[i]["type"] == "rest" or flags_of(i) == 0:
            i += 1
            continue
        j = i
        while (j + 1 < n and beat_index[j + 1] == beat_index[i]
               and events[j + 1]["type"] != "rest" and flags_of(j + 1) > 0):
            j += 1
        run = list(range(i, j + 1))
        if len(run) >= 2:
            max_flags = max(flags_of(k) for k in run)
            for level in range(1, max_flags + 1):
                has_level = [k for k in run if flags_of(k) >= level]
                for pos, k in enumerate(has_level):
                    if pos == 0:
                        state = "begin"
                    elif pos == len(has_level) - 1:
                        state = "end"
                    else:
                        state = "continue"
                    beams[k].append((level, state))
        i = j + 1
    return beams

# 장조 기준 fifths(조표) 테이블 — pc(0=C..11=B) -> fifths. 단조는 (pc+3)%12의 장조 값과 동일(같은 조표).
MAJOR_FIFTHS = {0: 0, 1: 7, 2: 2, 3: -3, 4: 4, 5: -1, 6: 6, 7: 1, 8: -4, 9: 3, 10: -2, 11: 5}

SHARP_SPELLING = {0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("D", 1), 4: ("E", 0), 5: ("F", 0),
                   6: ("F", 1), 7: ("G", 0), 8: ("G", 1), 9: ("A", 0), 10: ("A", 1), 11: ("B", 0)}
FLAT_SPELLING = {0: ("C", 0), 1: ("D", -1), 2: ("D", 0), 3: ("E", -1), 4: ("E", 0), 5: ("F", 0),
                  6: ("G", -1), 7: ("G", 0), 8: ("A", -1), 9: ("A", 0), 10: ("B", -1), 11: ("B", 0)}


def key_fifths(tonic_pc, mode):
    major_tonic_pc = tonic_pc if mode == "major" else (tonic_pc + 3) % 12
    fifths = MAJOR_FIFTHS[major_tonic_pc]
    # MAJOR_FIFTHS는 pc당 하나의 스펠링만 담고 있어 C#(7개 샵)처럼 극단값이 나올 수 있음 ->
    # 실제 악보 관례상 거의 항상 쓰는 enharmonic(Db, 5개 플랫)으로 접어준다.
    if fifths > 6:
        fifths -= 12
    elif fifths < -6:
        fifths += 12
    return fifths


def midi_to_pitch(midi, fifths):
    pc = midi % 12
    octave = midi // 12 - 1
    step, alter = (SHARP_SPELLING if fifths >= 0 else FLAT_SPELLING)[pc]
    return step, alter, octave


def scaled_durations(events, divisions=DIVISIONS, beats_per_measure=BEATS_PER_MEASURE):
    """각 이벤트의 분류된 음표값(점8분음표 등)을 실제 마디 길이(4박)에 딱 맞게 비례 조정한다.
    (검출 오차로 개별 노트 길이의 합이 정확히 4박이 되지 않는 경우가 대부분이라 필요)"""
    total_units = divisions * beats_per_measure
    raw_beats = [NOTE_VALUE_BEATS[e["note_value"]] for e in events]
    s = sum(raw_beats) or 1.0
    scaled = [max(1, round(b / s * total_units)) for b in raw_beats]
    diff = total_units - sum(scaled)
    scaled[-1] = max(1, scaled[-1] + diff)
    return scaled


def harmony_xml(root_pc, quality, fifths):
    step, alter = (SHARP_SPELLING if fifths >= 0 else FLAT_SPELLING)[root_pc]
    alter_xml = f"<root-alter>{alter}</root-alter>" if alter else ""
    kind, text = CHORD_KIND_BY_QUALITY[quality]
    return (
        f"<harmony><root><root-step>{step}</root-step>{alter_xml}</root>"
        f'<kind text="{text}">{kind}</kind></harmony>'
    )


def build_musicxml(notes_path, audio_path, title, override_bpm=None, chord_audio_path=None, manual_chords=None,
                    fingering_overrides=None, rhythm_grid=None, note_value_candidates=NOTE_VALUES):
    """manual_chords: {마디번호: (root_pc, quality)} — 사용자가 실제 악보/코드보로 확인해준 정답이
    있을 때 오디오 기반 코드 인식(chord_audio_path) 대신 그대로 사용한다.
    rhythm_grid/note_value_candidates: 단순한 리프(예: 4분/8분음표만 쓰는 곡)에서 피치 검출
    잡음으로 생긴 자잘한 조각들을 정리하고 싶을 때 snap_notes_to_grid()의 grid_beats 값과
    poc_rhythm_quantize.SIMPLE_NOTE_VALUES를 넘긴다."""
    notes = parse_notes(notes_path)
    notes = filter_scale_noise(notes)

    (corr, tonic, mode), _ = estimate_key(notes)
    fifths = key_fifths(tonic, mode)

    tempo, beat_times = detect_tempo_and_beats(audio_path)
    if override_bpm is not None:
        # quantize_notes는 beat_times[0](첫 비트 시점)만 앵커로 쓰고 나머지 배열은 안 씀 ->
        # 자동 감지된 템포가 틀렸을 때 앵커는 유지한 채 BPM 숫자만 정확한 값으로 교체 가능
        tempo = override_bpm
    if rhythm_grid is not None:
        notes = snap_notes_to_grid(notes, tempo, beat_times, grid_beats=rhythm_grid)
    quantized = quantize_notes(notes, tempo, beat_times, beats_per_measure=BEATS_PER_MEASURE,
                                note_value_candidates=note_value_candidates)
    path, groups = resolve_fingering(notes, fingering_overrides=fingering_overrides)

    if manual_chords is not None:
        chords = manual_chords
    elif chord_audio_path:
        chords = detect_chords(chord_audio_path, tempo, beat_times, beats_per_measure=BEATS_PER_MEASURE)
    else:
        chords = {}

    slide_starts, slide_stops = set(), set()
    for i, j in groups:
        slide_starts.add(i)
        slide_stops.add(j)

    # 크로매틱 런(경과음 3개 이상)은 실제 악보에서 중간 경과음을 낱개로 찍지 않고
    # "시작음 -> 슬라이드 -> 도착음" 두 노트만 표기한다(사용자가 실제 렌더된 악보를 보고
    # 직접 확인해준 표기 관례). 중간 경과음들의 박자 길이는 시작음 쪽으로 합쳐서
    # 마디 전체 길이 계산(scaled_durations)이 그대로 맞아떨어지게 한다.
    run_groups = [(i, j) for i, j in groups if j > i + 1]
    skip_idx = set()
    extra_beats = {}
    for i, j in run_groups:
        extra_beats[i] = extra_beats.get(i, 0.0) + sum(quantized[k]["beat_dur"] for k in range(i + 1, j))
        skip_idx.update(range(i + 1, j))

    quantized_by_measure = {}
    for i, (p, q) in enumerate(zip(path, quantized)):
        if i in skip_idx:
            continue
        s_idx, fret = p
        q = dict(q)
        if i in extra_beats:
            q["beat_dur"] = q["beat_dur"] + extra_beats[i]
            q["note_value"] = nearest_note_value(q["beat_dur"])
        q.update({"string": s_idx, "fret": fret, "note_idx": i})
        quantized_by_measure.setdefault(q["measure"], []).append(q)

    measures_xml = []
    for m in sorted(quantized_by_measure.keys()):
        events = insert_rests(quantized_by_measure[m], beats_per_measure=BEATS_PER_MEASURE,
                               note_value_candidates=note_value_candidates)
        durations = scaled_durations(events)
        beams = compute_beams(events)

        notes_xml = []
        for e, dur, beam_list in zip(events, durations, beams):
            note_type, dotted = NOTE_VALUE_TO_TYPE.get(e["note_value"], ("quarter", False))
            dot_xml = "<dot/>" if dotted else ""
            beam_xml = "".join(f'<beam number="{lv}">{st}</beam>' for lv, st in beam_list)

            if e["type"] == "rest":
                notes_xml.append(
                    f"<note><rest/><duration>{dur}</duration><voice>1</voice>"
                    f"<type>{note_type}</type>{dot_xml}{beam_xml}</note>"
                )
            else:
                s_idx, fret = e["string"], e["fret"]
                step, alter, octave = midi_to_pitch(e["midi"], fifths)
                alter_xml = f"<alter>{alter}</alter>" if alter else ""
                slide_xml = ""
                if e["note_idx"] in slide_stops:
                    slide_xml += '<slide type="stop"/>'
                if e["note_idx"] in slide_starts:
                    slide_xml += '<slide type="start" line-type="solid"/>'
                notes_xml.append(
                    f"<note><pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"
                    f'<duration>{dur}</duration><instrument id="P1-I1"/><voice>1</voice><type>{note_type}</type>{dot_xml}{beam_xml}'
                    f"<notations>{slide_xml}<technical><string>{s_idx + 1}</string><fret>{fret}</fret></technical></notations>"
                    f"</note>"
                )

        attrs_xml = ""
        if m == sorted(quantized_by_measure.keys())[0]:
            tuning = "".join(
                f'<staff-tuning line="{i + 1}"><tuning-step>{label[0]}</tuning-step>'
                f'<tuning-octave>{ {"G": 2, "D": 2, "A": 1, "E": 1}[label] }</tuning-octave></staff-tuning>'
                for i, (label, _) in enumerate(STRINGS)
            )
            attrs_xml = (
                f"<attributes><divisions>{DIVISIONS}</divisions>"
                f"<key><fifths>{fifths}</fifths><mode>{mode}</mode></key>"
                f"<time><beats>{BEATS_PER_MEASURE}</beats><beat-type>4</beat-type></time>"
                f'<clef><sign>TAB</sign><line>5</line></clef>'
                f"<staff-details><staff-lines>4</staff-lines>{tuning}</staff-details>"
                f"</attributes>"
            )

        chord_xml = harmony_xml(*chords[m], fifths) if m in chords else ""
        measures_xml.append(f'<measure number="{m}">{attrs_xml}{chord_xml}{"".join(notes_xml)}</measure>')

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">\n'
        '<score-partwise version="4.0">'
        f"<work><work-title>{sx.escape(title)}</work-title></work>"
        # GM 프로그램 34(1-based) = Electric Bass (finger). midi-instrument만 단독으론
        # (score-instrument 없이) 무시되고 적용 안 됐음 -> score-instrument를 다시 추가하되,
        # 이번엔 각 음표에도 <instrument id="P1-I1"/> 참조를 넣어서 어떤 음이 이 악기에
        # 속하는지 명시적으로 연결한다.
        '<part-list><score-part id="P1"><part-name>Bass</part-name>'
        '<score-instrument id="P1-I1"><instrument-name>Electric Bass</instrument-name></score-instrument>'
        '<midi-instrument id="P1-I1"><midi-channel>1</midi-channel><midi-program>34</midi-program></midi-instrument>'
        '</score-part></part-list>'
        f'<part id="P1">{"".join(measures_xml)}</part>'
        "</score-partwise>"
    )
    tonic_step, tonic_alter = (SHARP_SPELLING if fifths >= 0 else FLAT_SPELLING)[tonic]
    tonic_name = tonic_step + ("#" if tonic_alter > 0 else "b" if tonic_alter < 0 else "")
    return xml, {"tempo": tempo, "key": f"{tonic_name} {mode}", "measures": len(measures_xml)}


def main():
    audio_path = sys.argv[1] if len(sys.argv) > 1 else "일당백-데카당_mixed.mp3"
    notes_path = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"
    title = sys.argv[3] if len(sys.argv) > 3 else "일당백 · 데카당"
    output_path = sys.argv[4] if len(sys.argv) > 4 else "poc_score.musicxml"

    xml, info = build_musicxml(notes_path, audio_path, title)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"MusicXML 저장 완료: {output_path} (템포 {info['tempo']:.1f}, 조성 {info['key']}, 마디 {info['measures']})")


if __name__ == "__main__":
    main()
