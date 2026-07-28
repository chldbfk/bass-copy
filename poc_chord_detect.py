"""
Phase 1 PoC: 베이스 라인은 모노포닉이라 화성 정보를 다 담지 못하므로,
Demucs로 분리한 no_bass 스템(보컬+기타+키보드 등)에서 코드(근음 + 메이저/마이너/7th)를 추정한다.
1차 구현(마디별 크로마 템플릿 매칭)은 시간축 문맥이 없어 마디마다 코드가 튀는 문제가 있었음 ->
madmom의 사전학습 코드 인식 모델(DeepChroma + HMM 디코딩, 실제 사람이 라벨링한 코드 데이터셋으로 학습됨)이
설치되어 있으면 그걸 우선 쓰고, 없거나 실패하면 템플릿 매칭으로 폴백한다.
"""
import numpy as np
import librosa

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_NAME_TO_PC = {
    "C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4,
    "F": 5, "E#": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11, "Cb": 11,
}

# 코드 품질별 구성음(반음 간격, 근음 기준) — 템플릿 매칭 폴백에서 사용
CHORD_QUALITIES = {
    "": [0, 4, 7],
    "m": [0, 3, 7],
    "7": [0, 4, 7, 10],
    "m7": [0, 3, 7, 10],
    "maj7": [0, 4, 7, 11],
}


def _build_templates():
    names, templates = [], []
    for root in range(12):
        for quality, intervals in CHORD_QUALITIES.items():
            vec = np.zeros(12)
            vec[[(root + iv) % 12 for iv in intervals]] = 1.0
            templates.append(vec / np.linalg.norm(vec))
            names.append((root, quality))
    return names, np.stack(templates)


def chord_display_name(root_pc, quality):
    return f"{NOTE_NAMES[root_pc]}{quality}"


def _patch_madmom_py312_compat():
    """madmom 0.16.1(2018년 배포)이 Python 3.10+/numpy>=1.24에서 깨지는 부분을 임포트 전에 메꾼다:
    collections.MutableSequence 등은 3.10에서 collections.abc로 완전히 이동됐고,
    np.float/np.int 등의 deprecated 별칭은 numpy 1.24+에서 제거됨."""
    import collections
    import collections.abc
    for name in ["MutableSequence", "Iterable", "Mapping", "MutableMapping", "Sequence"]:
        if not hasattr(collections, name):
            setattr(collections, name, getattr(collections.abc, name))
    for name, alias in [("float", float), ("int", int), ("bool", bool), ("object", object), ("str", str), ("complex", complex)]:
        if not hasattr(np, name):
            setattr(np, name, alias)


def _parse_madmom_label(label):
    """madmom 코드 레이블('C#:maj', 'Bb:min', 'N' 등)을 (root_pc, quality)로 변환. 무코드(N/X)는 None."""
    if label in ("N", "X"):
        return None
    root_str, _, quality_str = label.partition(":")
    pc = NOTE_NAME_TO_PC.get(root_str)
    if pc is None:
        return None
    quality = {"maj": "", "min": "m", "maj7": "maj7", "min7": "m7", "7": "7"}.get(quality_str, "")
    return pc, quality


_madmom_processors = None  # (DeepChromaProcessor, DeepChromaChordRecognitionProcessor) 캐시 — 모델 로딩이 느림


def _get_madmom_processors():
    global _madmom_processors
    if _madmom_processors is None:
        _patch_madmom_py312_compat()
        from madmom.audio.chroma import DeepChromaProcessor
        from madmom.features.chords import DeepChromaChordRecognitionProcessor
        _madmom_processors = (DeepChromaProcessor(), DeepChromaChordRecognitionProcessor())
    return _madmom_processors


def detect_chords_madmom(audio_path, tempo, beat_times, beats_per_measure=4):
    """madmom의 사전학습 모델 + HMM 디코딩으로 시간 구간별 코드를 뽑고, 마디 중앙 시점 기준으로
    마디 번호 -> (root_pc, quality)에 매핑한다. HMM이 이미 시간축을 스무딩해주므로 마디마다
    코드가 튀는 문제가 템플릿 매칭보다 훨씬 적다."""
    dcp, decode = _get_madmom_processors()
    chroma = dcp(audio_path)
    segments = decode(chroma)

    beat_len = 60.0 / tempo
    first_beat = beat_times[0] if len(beat_times) > 0 else 0.0
    measure_len = beat_len * beats_per_measure

    last_time = float(segments[-1]["end"]) if len(segments) else 0.0
    num_measures = max(1, int((last_time - first_beat) / measure_len) + 1)

    chords = {}
    for m in range(1, num_measures + 1):
        center = first_beat + (m - 0.5) * measure_len
        seg = next((s for s in segments if s["start"] <= center < s["end"]), None)
        if seg is None:
            continue
        parsed = _parse_madmom_label(str(seg["label"]))
        if parsed is not None:
            chords[m] = parsed
    return chords


def detect_chords_template(audio_path, tempo, beat_times, beats_per_measure=4, min_confidence=0.55):
    """마디 번호(1-based) -> (root_pc, quality) 딕셔너리. 화성이 불분명한 마디는 항목 자체가 없음.
    보컬/드럼이 섞여 있어도 어느 정도 버티도록 harmonic-percussive 분리 후 크로마를 계산한다.
    madmom을 못 쓸 때의 폴백."""
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    y_harmonic = librosa.effects.harmonic(y, margin=8)
    chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)
    frame_times = librosa.frames_to_time(np.arange(chroma.shape[1]), sr=sr)

    beat_len = 60.0 / tempo
    first_beat = beat_times[0] if len(beat_times) > 0 else 0.0
    measure_len = beat_len * beats_per_measure

    names, templates = _build_templates()
    last_time = frame_times[-1] if len(frame_times) else 0.0
    num_measures = max(1, int((last_time - first_beat) / measure_len) + 1)

    chords = {}
    for m in range(1, num_measures + 1):
        m_start = first_beat + (m - 1) * measure_len
        m_end = m_start + measure_len
        mask = (frame_times >= m_start) & (frame_times < m_end)
        if not mask.any():
            continue
        vec = chroma[:, mask].mean(axis=1)
        norm = np.linalg.norm(vec)
        if norm < 1e-6:
            continue
        vec = vec / norm
        scores = templates @ vec
        best = int(np.argmax(scores))
        if scores[best] < min_confidence:
            continue
        chords[m] = names[best]
    return chords


def detect_chords(audio_path, tempo, beat_times, beats_per_measure=4, min_confidence=0.55):
    """madmom(사전학습+HMM)을 우선 쓰고, 임포트/실행에 실패하면 템플릿 매칭으로 폴백한다."""
    try:
        return detect_chords_madmom(audio_path, tempo, beat_times, beats_per_measure=beats_per_measure)
    except Exception as e:
        print(f"[poc_chord_detect] madmom 사용 불가({e!r}), 템플릿 매칭으로 폴백")
        return detect_chords_template(
            audio_path, tempo, beat_times, beats_per_measure=beats_per_measure, min_confidence=min_confidence
        )
