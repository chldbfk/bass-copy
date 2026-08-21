"""회귀 테스트 곡 목록(fixtures). 각 항목은 사용자가 원곡 대조로 직접 검증한
'정답'이 있는 곡만 등록한다 — 새 곡을 처리하다 파이프라인 코드(poc_*.py)를 고칠 때마다
이 곡들의 결과가 그대로 유지되는지 자동으로 확인하기 위함(회귀 방지). 검증 안 된 곡을
여기 넣으면 틀린 결과가 "정답"으로 고정돼버리므로 절대 넣지 말 것.

새 곡을 검증 완료했다면 여기에 추가하고 `python tests/regression/run.py --update`로
골든 스냅샷을 만들 것 — 그 전에 반드시 사람이 그 곡의 결과(마디 수·노트·슬라이드)를
원곡/직접 만든 정답 TAB과 대조해 확인부터 할 것.

주의: override_bpm/override_first_beat은 반드시 명시적으로 고정할 것 — 자동감지
(librosa beat_track)는 재실행마다 값이 흔들릴 수 있음(실측: 나는나비에서 같은 입력인데
자동감지 결과가 126.0 -> 129.20으로 바뀌면서 마디 수가 9 -> 10으로 밀리는 걸 확인,
2026-08-21). 이 테스트의 목적은 오디오 분석 자체의 비결정성이 아니라 "파이프라인 코드가
실제로 바뀌었는지"만 검증하는 것이므로, 이미 검증된 세션에서 쓴 값을 그대로 고정한다.

곡별 원시 노트 텍스트(notes_path)는 Demucs+torchcrepe 추출 후 필요한 수동 교정
(노이즈 제거·grid snap 등, 각 곡 세션에서 이미 끝난 상태)이 반영된 파일을 그대로 쓴다 —
이 회귀 테스트는 오디오 추출(느리고 약간 비결정적) 단계는 건드리지 않고, 그 다음
단계(스케일필터/운지최적화/리듬정렬/렌더링)만 검증 대상으로 삼는다. 지금까지 발견된
버그(MusicXML 템포 태그 누락, 마디 앵커 밀림, ASCII 라벨 합계 불일치, 크로매틱 런
오적용)가 전부 이 계층에서 났기 때문.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _p(*parts):
    return os.path.join(ROOT, *parts)


FIXTURES = [
    {
        "name": "나는나비",
        "notes_path": _p("songs", "나는나비", "outputs", "poc_output_나는나비_snapped.txt"),
        "audio_path": _p("songs", "나는나비", "나는나비.mp3"),
        "title": "나는나비",
        "override_bpm": 126.0,
        "note_value_candidates": None,  # infer_note_grid가 SIMPLE로 자동판단(검증됨)
        "apply_chromatic_slides": True,  # 이 곡은 크로매틱 런 0건이라 값 자체는 영향 없음
        # 2026-08-21(같은 날 후속 세션): 마디 4 라벨 합계가 4.5박으로 나오던 버그, 원래는
        # "_close_measure_labels()의 보정 한계"로 추정했었으나 실제 원인은 quantize_notes()의
        # 마디 경계 반올림 오차(마디4→5 경계에서 beat_pos가 16.0보다 1e-6만큼 모자라 EPS를
        # 더해도 여전히 마디4로 계산되는데, 나머지값을 반올림하면 4.0이 되어버려 마디5 1박에
        # 있어야 할 노트가 마디4에 갇힘)로 밝혀져 수정 완료 — known_label_sum_issues 제거함.
        # 같은 세션에서 poc_tab_render.transition_cost()의 개방현 보너스 중복 계산 버그도
        # 고쳐서 마디7·8의 A1 반복 구간 운지(A현 개방현 -> E현5프렛)가 바뀜.
        "verified_note": "9마디/71노트, 마디2~9는 사용자 정답 TAB과 완전 일치(마디1 첫 노트만 "
                          "인트로 클립 노이즈로 사용자가 확인 후 수동 보정). 2026-08-21 검증. "
                          "같은 날 후속 수정(마디4 경계 반올림, 마디7·8 개방현 운지)도 "
                          "사용자 재확인 완료, golden 갱신됨.",
    },
    {
        "name": "돈룩백",
        "notes_path": _p("songs", "돈룩백", "outputs", "poc_output_돈룩백.txt"),
        "audio_path": _p("songs", "돈룩백", "돈룩백.mp3"),
        "title": "돈룩백",
        "override_bpm": 80.75,
        "note_value_candidates": "NOTE_VALUES",  # 문자열로 표기, run.py에서 실제 객체로 치환
        "override_first_beat": 0.0,
        "apply_chromatic_slides": False,  # 빠른 곡(원곡 161.5 BPM)이라 크로매틱 런이 실제로는
                                           # 슬라이드가 아니라 개별 16분음표였음(사용자 확인).
        "verified_note": "8마디/70노트, 노트 데이터 자체가 사용자의 원곡 대조 정답 TAB으로 "
                          "재구성됨(수기 교정) — 알고리즘의 잔여 오차(지속음 과분절)는 이미 "
                          "보정된 입력을 씀으로써 우회한 상태. 2026-08-21 검증. 같은 날 후속 "
                          "수정(개방현 보너스 중복계산, enforce_pitch_consistency 다수결 원복)으로 "
                          "A1 반복구간(마디2,4,6,8 전부)이 E현5프렛으로 완전 통일됨 — 이전까지 "
                          "미해결로 남아있던 항목(b)이 이걸로 해결.",
    },
    {
        "name": "Stand-By-Me",
        "notes_path": _p("songs", "Stand-By-Me", "outputs", "poc_output_Stand-By-Me.txt"),
        "audio_path": _p("songs", "Stand-By-Me", "Stand-By-Me.mp3"),
        "title": "Stand By Me",
        "override_bpm": 120.0,
        "note_value_candidates": None,  # infer_note_grid가 SIMPLE로 자동판단(검증됨)
        "apply_chromatic_slides": True,  # F2->E2->D#2 크로매틱 슬라이드 1건, 사용자 확인됨
        "fingering_overrides": {45: (1, 7)},  # A2(midi45) 반복 리프를 D현(인덱스1) 7프렛으로
        # 통일 — 다수결(=G현2프렛, 11 vs 5회)이 아니라 사용자가 직접 "D현7프렛으로 통일해야
        # 함"이라고 확정 지정한 값. 다수결과 실제 정답이 다를 수 있다는 걸 보여준 사례라
        # override로 명시함(추측하지 말고 항상 이렇게 확정값을 남길 것).
        "verified_note": "11마디/48노트, A major. 2026-08-21: 파일 드리프트(37노트/D현7프렛으로 "
                          "되돌아가 있던 것) 발견 후 Demucs 결과는 재사용하고 torchcrepe만 재추출, "
                          "이전 확정 보정(첫노트 F1->F2, 12.84-13.08s G#2 노이즈 제거) 재적용해 "
                          "48노트로 복구. 반복되는 A2 리프(16회 전체)를 하나로 통일해야 한다고 "
                          "사용자가 확인했는데, 자동 다수결은 G현2프렛을 골랐지만 실제로는 "
                          "D현7프렛이 맞다고 정정받아 fingering_overrides로 고정.",
    },
]
