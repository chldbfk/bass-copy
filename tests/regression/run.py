"""파이프라인 회귀 테스트. tests/regression/fixtures.py에 등록된, 사람이 원곡 대조로
이미 검증한 곡들에 대해 build_musicxml + ASCII TAB 생성을 다시 돌려서
tests/regression/golden/ 아래 저장된 스냅샷과 정확히 같은 결과가 나오는지 확인한다.

목적: 새 곡을 처리하다가 poc_*.py 파이프라인 코드를 고칠 때, 그 수정이 이미 검증 끝난
예전 곡들의 결과를 조용히 깨뜨리지 않았는지 자동으로 잡아내기 위함(2026-08-21, 회귀
테스트 부재 문제 제기로 신설). 지금까지 실제로 발견된 버그(MusicXML 템포 태그 누락,
마디 앵커 밀림, ASCII 라벨 합계 불일치, 크로매틱 런 오적용)가 전부 오디오 추출 이후
계층(스케일필터/운지최적화/리듬정렬/렌더링)에서 났으므로, 느리고 약간 비결정적인
Demucs/torchcrepe 추출은 다시 돌리지 않고 이미 추출·교정된 notes.txt를 고정 입력으로
삼아 그 다음 단계만 검증한다.

사용법 (프로젝트 루트에서):
  python tests/regression/run.py           # 검증만(기본) — golden과 다르면 실패(exit 1)
  python tests/regression/run.py --update  # 지금 결과를 새 golden으로 저장/갱신
                                            # (반드시 사람이 결과를 원곡과 대조 확인한 뒤에만 사용.
                                            #  검증 없이 --update하면 틀린 결과가 그대로 "정답"이
                                            #  되어버려 이후 진짜 회귀를 걸러내지 못하게 됨.)
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# Windows 콘솔이 cp949 기본이라 한글/em-dash 등을 출력하다 UnicodeEncodeError로
# 죽는 경우가 있어(2026-08-21 최초 실행 중 발견) UTF-8로 강제 전환.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from poc_tab_render import parse_notes, filter_scale_noise, resolve_fingering  # noqa: E402
from poc_rhythm_quantize import (  # noqa: E402
    detect_tempo_and_beats, quantize_notes, infer_note_grid, NOTE_VALUES, SIMPLE_NOTE_VALUES,
)
from poc_final_tab import render_tab_by_measure  # noqa: E402
from poc_export_musicxml import build_musicxml  # noqa: E402

from fixtures import FIXTURES  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")

NAME_TO_BEATS = {name: beats for beats, name in NOTE_VALUES}
NOTE_VALUE_SETS = {"NOTE_VALUES": NOTE_VALUES, "SIMPLE_NOTE_VALUES": SIMPLE_NOTE_VALUES}


def _label_beats(label):
    label = label.replace("(슬라이드)", "").replace("쉼표", "음표")
    return NAME_TO_BEATS[label]


def _measure_beat_sums(ascii_tab):
    """각 마디 '음표:' 라벨 줄을 실제 박자로 역산해 합계를 낸다 — 2026-08-12 나는나비
    세션에서 발견된 '라벨 합계가 4박을 넘는' 버그 클래스를 golden 대조와 무관하게
    항상 잡아내기 위한 불변조건 검사용."""
    sums = []
    for line in ascii_tab.splitlines():
        if line.startswith("   음표: "):
            labels = line[len("   음표: "):].split()
            sums.append(round(sum(_label_beats(l) for l in labels), 6))
    return sums


def run_fixture(fx):
    note_value_candidates = fx.get("note_value_candidates")
    if isinstance(note_value_candidates, str):
        note_value_candidates = NOTE_VALUE_SETS[note_value_candidates]

    apply_slides = fx.get("apply_chromatic_slides", True)
    override_first_beat = fx.get("override_first_beat")
    fingering_overrides = fx.get("fingering_overrides")  # {midi: (string_idx, fret)} —
    # enforce_pitch_consistency의 다수결보다 사용자가 직접 확인해준 자리를 우선시할 때 씀
    # (예: Stand-By-Me A2 리프, 2026-08-21 사용자가 D현7프렛으로 통일해달라고 확인).

    # --- MusicXML: build_musicxml이 내부에서 parse/filter/resolve/quantize를 전부 다시 수행 ---
    xml, info = build_musicxml(
        fx["notes_path"], fx["audio_path"], fx["title"],
        override_bpm=fx["override_bpm"],
        note_value_candidates=note_value_candidates,
        override_first_beat=override_first_beat,
        apply_chromatic_slides=apply_slides,
        fingering_overrides=fingering_overrides,
    )

    # --- ASCII TAB: render_tab_by_measure는 별도 조합이 필요(SKILL.md 4번 방식과 동일 순서) ---
    notes = parse_notes(fx["notes_path"])
    notes = filter_scale_noise(notes)
    tempo = fx["override_bpm"]
    _, beat_times = detect_tempo_and_beats(fx["audio_path"])
    if override_first_beat is not None:
        beat_times = [override_first_beat]
    nvc = note_value_candidates if note_value_candidates is not None else infer_note_grid(notes, tempo)
    quantized = quantize_notes(notes, tempo, beat_times, note_value_candidates=nvc)
    path, groups = resolve_fingering(notes, apply_chromatic_slides=apply_slides,
                                      fingering_overrides=fingering_overrides)
    ascii_tab = render_tab_by_measure(notes, path, quantized, groups=groups)

    measure_beat_sums = _measure_beat_sums(ascii_tab)
    tempo_tag_present = f'sound tempo="{tempo:.2f}"' in xml

    return {
        "note_count": len(notes),
        "tempo": round(info["tempo"], 2),
        "key": info["key"],
        "measures": info["measures"],
        "slide_group_count": len(groups),
        "slide_groups": [list(g) for g in groups],
        "measure_beat_sums": measure_beat_sums,
        "tempo_tag_present": tempo_tag_present,
        "ascii_tab": ascii_tab,
        "musicxml": xml,
    }


def _diff_summary(golden, actual):
    diffs = []
    for key in ("note_count", "tempo", "key", "measures", "slide_group_count",
                "slide_groups", "measure_beat_sums", "tempo_tag_present"):
        if golden.get(key) != actual.get(key):
            diffs.append(f"  {key}: golden={golden.get(key)!r}  actual={actual.get(key)!r}")
    if golden.get("ascii_tab") != actual.get("ascii_tab"):
        diffs.append("  ascii_tab: 내용 다름")
    if golden.get("musicxml") != actual.get("musicxml"):
        diffs.append("  musicxml: 내용 다름")
    return diffs


def main():
    update = "--update" in sys.argv
    os.makedirs(GOLDEN_DIR, exist_ok=True)

    failed = []
    for fx in FIXTURES:
        name = fx["name"]
        print(f"=== {name} ===")
        actual = run_fixture(fx)

        # 파이프라인 알고리즘이 항상 지켜야 하는 불변조건(과거 실제로 깨졌던 버그들) —
        # golden 스냅샷 유무·일치 여부와 무관하게 매번 검사한다. known_label_sum_issues에
        # 등록된 (마디, 기존 합계) 조합은 이미 문서화된 미해결 버그이므로 통과시키되,
        # 그 문서화된 값과도 다르면(더 나빠지거나 바뀌면) 새로운 이상으로 보고 실패시킨다.
        known_issues = fx.get("known_label_sum_issues", {})
        invariant_fail = False
        for i, s in enumerate(actual["measure_beat_sums"], 1):
            if abs(s - 4.0) <= 1e-6:
                continue
            if i in known_issues and abs(s - known_issues[i]) <= 1e-6:
                print(f"  [알려진 미해결 버그] 마디 {i} 라벨 합계 = {s}박 (문서화된 값과 일치, 통과 처리)")
                continue
            print(f"  [불변조건 위반] 마디 {i} 라벨 합계 = {s}박 (4.0이어야 함)")
            invariant_fail = True
        if not actual["tempo_tag_present"]:
            print(f"  [불변조건 위반] MusicXML에 실제 템포({actual['tempo']}) <sound tempo> 태그 없음")
            invariant_fail = True
        if invariant_fail:
            failed.append(name)
            continue

        golden_path = os.path.join(GOLDEN_DIR, f"{name}.json")
        if update or not os.path.exists(golden_path):
            with open(golden_path, "w", encoding="utf-8") as f:
                json.dump(actual, f, ensure_ascii=False, indent=2)
            print(f"  golden 저장/갱신 완료: {golden_path}")
            if fx.get("verified_note"):
                print(f"  ({fx['verified_note']})")
            continue

        with open(golden_path, encoding="utf-8") as f:
            golden = json.load(f)
        diffs = _diff_summary(golden, actual)
        if diffs:
            print("  [실패] golden과 다름:")
            for d in diffs:
                print(d)
            failed.append(name)
        else:
            print(f"  [통과] golden과 일치 (노트{actual['note_count']}개, {actual['measures']}마디, "
                  f"{actual['tempo']}BPM, 슬라이드{actual['slide_group_count']}건)")

    print()
    if failed:
        print(f"실패: {', '.join(failed)}")
        sys.exit(1)
    print(f"전체 통과 ({len(FIXTURES)}곡)")


if __name__ == "__main__":
    main()
