---
name: tab-score-pipeline
description: mp3 음원에서 베이스 라인 AI TAB 악보(ASCII TAB + MusicXML + AlphaTab HTML)를 끝까지 생성하는 파이프라인. "악보 생성해줘", "TAB 만들어줘", "이 곡도 악보 뽑아줘" 같은 요청에 사용. 창업동아리 AI TAB 악보 앱 프로젝트(타브악보_프로젝트) 전용.
---

# 베이스 TAB 악보 생성 파이프라인

곡 mp3 하나를 받아서 Demucs 음원분리 → torchcrepe 피치 추출 → 스케일 필터링 → 리듬 정렬 → 운지 최적화(슬라이드 포함) → ASCII TAB / MusicXML / AlphaTab HTML까지 끝까지 생성한다. 작업 위치는 `타브악보_프로젝트/` 폴더(이 SKILL.md 기준 두 단계 위).

**정리 원칙**: 파일을 다 만든 뒤에 나중에 몰아서 정리하지 말고, **생성하는 시점부터** 아래 폴더 구조에 맞는 위치에 바로 쓸 것.
- 곡별 산출물(노트 텍스트, TAB, MusicXML, HTML, 분리된 오디오)은 전부 `songs/<곡이름>/` 밑에 (원본 mp3는 `songs/<곡이름>/`, 결과물은 `songs/<곡이름>/outputs/`, Demucs 결과는 `songs/<곡이름>/separated/`) — 프로젝트 루트에 곡 관련 파일을 직접 두지 않는다.
- 새로운 곡을 시작하면 제일 먼저 `songs/<곡이름>/outputs/` 폴더부터 만들고 시작한다.
- 기획/회의/기록류 문서는 `docs/`에.
- 기존 카테고리(스크립트/`docs`/`songs`/라이브러리)에 안 맞는 새로운 종류의 파일이 생기면, 대충 루트에 끼워넣지 말고 적절한 새 폴더를 만들어 분류할 것(예: 나중에 프론트엔드 코드가 생기면 `app/` 같은 새 최상위 폴더).

## 0. 폴더 구조 (2026-07-24 정리됨)

```
타브악보_프로젝트/
├── poc_*.py              # 파이프라인 스크립트 전부 (여기 그대로 유지, 서로 import함)
├── alphatab_lib/         # AlphaTab 런타임 의존성(JS/폰트) — 루트 기준 상대경로로 참조되므로 이동 금지
├── alphatab_source/      # 참고용 alphaTab 소스 클론(런타임 미사용)
├── docs/                 # 계획서·기획 문서
│   └── 타브 악보 작업 계획서.md
└── songs/<곡이름>/       # 곡별 데이터 — 여기가 늘어나는 부분
    ├── <곡이름>.mp3
    ├── separated/        # Demucs 결과 (bass.wav, no_bass.wav)
    └── outputs/          # poc_output_*.txt, poc_final_tab_output_*.txt, poc_score_*.musicxml, poc_score_alphatab_*.html
```

**스크립트는 항상 프로젝트 루트(`타브악보_프로젝트/`)에서 실행**하고, 입출력 경로는 `songs/<곡이름>/...`로 지정한다(스크립트 자체를 옮기지 않았으므로 import는 그대로 동작).

## 1. 준비 + 음원 분리 (Demucs)

- 입력 mp3를 `songs/<곡이름>/<곡이름>.mp3`로 배치한다 (폴더 없으면 생성).
- 콘솔 출력이 cp949로 깨져 보여도(한글 로그) 정상 동작이니 무시해도 됨 — 결과 파일은 UTF-8로 저장됨.

```bash
cd "songs/<곡이름>" && demucs --two-stems=bass "<곡이름>.mp3" && cd ../..
mv "songs/<곡이름>/separated/htdemucs/<곡이름>/"* "songs/<곡이름>/separated/" && rmdir -p "songs/<곡이름>/separated/htdemucs/<곡이름>" 2>/dev/null
```
(demucs가 `separated/htdemucs/<곡이름>/bass.wav` 형태로 만들어내므로, `songs/<곡이름>/separated/bass.wav`가 되도록 한 단계 정리해도 되고, 중첩 그대로 둬도 무방 — 다음 단계에서 정확한 경로만 넘기면 됨)

## 2. 피치 추출 (torchcrepe)

```
python poc_pitch_extract.py "songs/<곡이름>/separated/bass.wav" "songs/<곡이름>/outputs/poc_output_<곡이름>.txt"
```

FMIN=35Hz 하한 유지(더 낮추면 torchcrepe 0.0.24의 음수 인덱스 버그 발생). 결과는 `시작s ~ 끝s (길이s)  음이름옥타브` 형식의 노트 시퀀스.

## 3. 사용자 확인이 필요한 지점 (반드시 먼저 물어볼 것)

파이프라인을 계속 돌리기 전에 아래 두 가지는 **추측하지 말고 사용자에게 확인**한다:

1. **베이스가 실제로 언제부터/언제까지 연주되는지**: Demucs 분리가 완벽하지 않아서 다른 악기 소리가 bass.wav에 섞여 들어와(bleed) 인트로/아웃트로에 가짜 노트가 잡히는 경우가 흔함. 사용자가 "베이스는 N초부터 등장/M초까지만 연주" 라고 알려주면, 그 범위 밖 노트를 `songs/<곡이름>/outputs/poc_output_<곡이름>.txt`에서 직접 제거한다(정규식으로 시작 시각 필터링). (계획서.md 11-3 섹션: 향후 RMS 에너지 기반 반자동 추정으로 전환 예정 — 아직 미구현)
2. **BPM 자동감지가 맞는지**: `librosa.beat.beat_track`은 옥타브 오류(2배/0.5배, 3:2, 4:3 등)에 취약함. 사용자가 "이거 너무 빠른/느린 것 같다"고 하면, 정확한 BPM을 아는지 먼저 묻고, 모르면 절반/2배 등의 후보를 제시해서 고르게 한다. → `override_bpm` 파라미터로 바로 교정 가능(재추출 불필요). 자세한 배경: 메모리 `feedback_bpm_manual_override`.

## 4. 최종 TAB(ASCII) + MusicXML + AlphaTab HTML 생성

핵심 로직은 전부 `poc_tab_render.py`의 `resolve_fingering(notes)` 하나에 통합되어 있다 (스케일 필터링은 별개, `filter_scale_noise`). 개별 스크립트에서 직접 호출하지 말고 항상 이 함수를 거칠 것:

```python
from poc_tab_render import parse_notes, filter_scale_noise, resolve_fingering
notes = parse_notes("songs/<곡이름>/outputs/poc_output_<곡이름>.txt")
notes = filter_scale_noise(notes)          # 스케일 밖 + 극단 노이즈 제거 (크로매틱 런은 보호됨)
path, groups = resolve_fingering(notes)     # (줄,프렛) 경로 + 슬라이드로 처리된 (시작idx,끝idx) 그룹들
```

- **ASCII TAB**: `poc_final_tab.py`의 `render_tab_by_measure(notes, path, quantized, groups=groups)` — 슬라이드는 "시작프렛/끝프렛" 한 칸으로 압축 표기(`3/6`).
- **MusicXML**: `poc_export_musicxml.py`의 `build_musicxml(notes_path, audio_path, title, override_bpm=...)` — 슬라이드는 `<slide type="start"/>`~`<slide type="stop"/>`로 시작/끝 노트만 남기고 **중간 경과음은 완전히 생략**(박자 길이는 시작음에 합산). 조성 추정(Krumhansl-Schmuckler)에 따라 조표·음이름 스펠링 자동 결정.
- **AlphaTab HTML**: `poc_export_alphatab_html.py`의 `main()` — MusicXML을 alphaTab.min.js(인라인 임베드)로 렌더링한 단일 HTML. `LIB_DIR = "alphatab_lib"`이 **프로젝트 루트 기준 상대경로**이므로 스크립트를 반드시 루트에서 실행할 것. CLI: `python poc_export_alphatab_html.py <mp3경로> <notes.txt경로> "<제목>" <output.html경로> [override_bpm]`

전형적인 실행 (BPM 교정이 필요한 경우, `<곡폴더>` = `songs/<곡이름>`):
```bash
python -c "
from poc_export_musicxml import build_musicxml
xml, info = build_musicxml('<곡폴더>/outputs/poc_output_<곡이름>.txt', '<곡폴더>/<곡이름>.mp3', '<제목>', override_bpm=71.8)
open('<곡폴더>/outputs/poc_score_<곡이름>.musicxml','w',encoding='utf-8').write(xml)
"
python poc_export_alphatab_html.py "<곡폴더>/<곡이름>.mp3" "<곡폴더>/outputs/poc_output_<곡이름>.txt" "<제목>" "<곡폴더>/outputs/poc_score_alphatab_<곡이름>.html" 71.8
```

## 5. 결과 공유

생성된 `poc_score_alphatab_<곡이름>.html`을 Artifact로 게시한다. 곡을 바꿔가며 같은 세션에서 반복 작업할 땐 **같은 file_path로 재게시**하면 URL이 유지됨. favicon은 🎸로 통일.

## 6. 슬라이드 판정 로직 — 왜 이렇게 짜여 있는지

`poc_tab_render.py`에 3종류의 슬라이드 탐지기가 있고, `resolve_fingering()`이 이들을 전부 적용한 뒤 위치를 전파한다:

1. `detect_octave_slides` — 정확히 1옥타브(12반음) 차이 + 간격 0.6s 이내 → 같은 줄에서 12프렛 이동.
2. `find_chromatic_runs` — 반음씩 3개 이상 연속 상승/하강 + 간격 0.15s 이내 → 같은 줄 연속 프렛. `filter_scale_noise`가 이 구간을 노이즈로 오인해 지우지 않도록 보호도 함께 함.
3. `detect_leap_slides` (`VALIDATED_LEAP_SLIDES`) — 위 두 규칙에 안 걸리는 특정 (출발음,도착음) MIDI 쌍만 좁게 매칭. **일반적인 "반음차+간격" 임계값으로 넓히면 안 됨** — 실제로 같은 곡 안에서도 슬라이드가 아닌 유사 패턴(예: 하행 2반음, 비슷한 간격)이 있어서 오탐이 났었음. 새 슬라이드 패턴을 발견하면 이 리스트에 검증된 쌍만 추가할 것.

그리고 `propagate_slide_landing()`이 슬라이드 도착 직후 "같은 음이 반복되는 구간"을 도착 위치(같은 프렛, 인접 줄)로 이어붙인다 — 이게 없으면 대칭 윈도우 중앙값 앵커가 아직 안 고쳐진 다수의 예전 프렛에 표가 쏠려서 슬라이드 직후에도 부자연스러운 위치로 돌아가 버림.

**중요**: 이 슬라이드 판정은 노트 목록(이산 데이터)만으로는 한계가 있다. 실제로 슬라이드인지 아닌지는 사용자가 원곡을 듣고 확인해줘야 확실하다 — 자동 탐지 결과를 사용자에게 보여주고 검증받는 과정을 항상 거칠 것 (사용자가 "이거 슬라이드로 처리해야 편해" 같은 피드백을 주면 [[feedback_chromatic_run_slide_fingering]] 참고해서 반영).

## 7. 검증 방법 (사용자가 직접 TAB을 고쳐줄 때)

사용자가 생성된 `poc_final_tab_output_*.txt`를 직접 손으로 고쳐서 "정답"을 만들어주는 경우가 있다. 이때는:
1. 원본을 별도 파일로 백업(`cp`)해두고 diff로 정확히 어디가 바뀌었는지 확인.
2. ASCII 그리드는 눈대중으로 칸을 세지 말고, 파이썬으로 (마디, 노트 인덱스, 줄, 프렛)을 직접 뽑아서 비교할 것 — 슬라이드 셀("3/6")처럼 폭이 다른 칸이 섞이면 텍스트 정렬만 보고는 어디가 바뀐 건지 착각하기 쉬움.
3. 발견한 패턴을 일반화하기 전에 곡 전체에서 오탐이 없는지 반드시 재검증.

## 참고 문서

- `docs/타브 악보 작업 계획서.md` — 전체 기획 배경, PoC 진행 기록(9번 섹션), **11번 섹션(악보 생성 품질 기준)** — 앱 출시라는 최종 목표를 기준으로 피치인식/BPM/노이즈판별/슬라이드/검증프로세스 항목별 결정사항 정리
- 메모리: `project_tab_score_app`(진행상황 — 최신 핵심 프레임 포함), `feedback_bpm_manual_override`, `feedback_chromatic_run_slide_fingering`(이 세션에서 배운 슬라이드 처리 교훈)
- **최종 목표 리마인더**: 이 프로젝트의 목적은 개별 곡 악보를 예쁘게 뽑는 게 아니라 **앱 출시**임. 곡별 작업은 파이프라인 정확도를 쌓는 테스트 과정 — 계획서 11번 섹션 참고.
