"""
Phase 0 PoC 통합: 스케일 기반 노이즈 필터링 -> 박자/마디 정렬 -> 포지션 앵커 기반
운지 최적화 -> 마디선이 있는 최종 TAB 렌더링까지 전체 파이프라인을 하나로 묶는다.
"""
import sys

from poc_tab_render import parse_notes, filter_scale_noise, resolve_fingering, STRINGS
from poc_rhythm_quantize import detect_tempo_and_beats, quantize_notes


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


def render_tab_by_measure(notes, path, quantized, groups=()):
    units = build_display_units(notes, groups)

    # 렌더링 단위 -> 마디 번호 매핑 (단위의 시작 노트 기준)
    measures = {}
    for i, j in units:
        s_idx, fret_start = path[i]
        _, fret_end = path[j]
        cell = f"{fret_start}/{fret_end}" if j > i else str(fret_start)
        q_start, q_end = quantized[i], quantized[j]
        value = q_start["note_value"] if j == i else f"{q_start['note_value']}(슬라이드)"
        measures.setdefault(q_start["measure"], []).append(
            {"string": s_idx, "cell": cell, "value": value, "start": q_start["start"], "end": q_end["end"]}
        )

    out = []
    for m in sorted(measures.keys()):
        entries = measures[m]
        out.append(f"[마디 {m}] ({entries[0]['start']:.1f}s ~ {entries[-1]['end']:.1f}s)")
        widths = [max(len(e["cell"]), 2) for e in entries]
        for si, (label, _) in enumerate(STRINGS):
            cells = [e["cell"].rjust(w) if e["string"] == si else "-" * w for e, w in zip(entries, widths)]
            out.append(f"{label}|-" + "-".join(cells) + "-|")
        values = " ".join(e["value"] for e in entries)
        out.append(f"   음표: {values}")
        out.append("")
    return "\n".join(out)


def main():
    audio_path = sys.argv[1] if len(sys.argv) > 1 else "일당백-데카당_mixed.mp3"
    notes_path = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"
    output_path = sys.argv[3] if len(sys.argv) > 3 else "poc_final_tab_output.txt"

    print(f"[1/4] 노트 파싱: {notes_path}")
    notes = parse_notes(notes_path)

    print("[2/4] 스케일 기반 노이즈 필터링")
    notes = filter_scale_noise(notes)

    print(f"[3/4] 템포/비트 감지: {audio_path}")
    tempo, beat_times = detect_tempo_and_beats(audio_path)
    print(f"  추정 템포: {tempo:.1f} BPM")
    quantized = quantize_notes(notes, tempo, beat_times)

    print("[4/4] 운지 최적화 및 렌더링")
    path, groups = resolve_fingering(notes)

    tab_text = render_tab_by_measure(notes, path, quantized, groups=groups)
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
