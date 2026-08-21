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
        # 알려진 미해결 버그(2026-08-21 나는나비 세션에서 발견, 의도적으로 보류됨):
        # _close_measure_labels()의 보정 한계로 마디 4의 ASCII 라벨 합계가 4.0이 아니라
        # 4.5박으로 표시됨(내부 커서/MusicXML 실제 박자는 정확 — 표시 라벨만 문제).
        # 근본 원인(디케이 과분절)을 먼저 줄이는 게 우선이라 아직 고치지 않기로 함
        # — 여기 명시해서 이 회귀 테스트가 매번 실패로 막지 않게 하되, 값이 이 문서화된
        # 수치에서 더 벗어나면(개선이든 악화든) 바로 드러나도록 한다.
        "known_label_sum_issues": {4: 4.5},
        "verified_note": "9마디/71노트, 마디2~9는 사용자 정답 TAB과 완전 일치(마디1 첫 노트만 "
                          "인트로 클립 노이즈로 사용자가 확인 후 수동 보정). 2026-08-21 검증.",
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
                          "보정된 입력을 씀으로써 우회한 상태. 2026-08-21 검증.",
    },
    # Stand-By-Me: 2026-08-21 기준 songs/Stand-By-Me/outputs/poc_output_Stand-By-Me.txt가
    # 문서화된 검증 상태(48노트, G현2프렛 리프)와 다른 예전 상태(37노트, D현7프렛)로 되돌아가
    # 있는 게 발견됨 — 원인 미상(어느 세션에선가 재실행되며 덮어써진 것으로 추정, 백업 없음).
    # 48노트 상태로 복구(Demucs+torchcrepe 재추출 후 재검증) 후에만 여기 추가할 것.
    # 그 전까지는 검증된 곡이 2개뿐이므로, 새 곡 작업 중 이 회귀 테스트가 실패하면 반드시
    # 진지하게 원인을 볼 것 — 지금 곡 수가 적을수록 각 실패의 신뢰도가 더 중요함.
]
