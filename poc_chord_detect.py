"""
Phase 1 PoC: 베이스 라인은 모노포닉이라 화성 정보를 다 담지 못하므로,
Demucs로 분리한 no_bass 스템(보컬+기타+키보드 등)에서 크로마 특징을 뽑아
마디 단위로 코드(근음 + 메이저/마이너/7th)를 템플릿 매칭으로 추정한다.
"""
import numpy as np
import librosa

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# 코드 품질별 구성음(반음 간격, 근음 기준)
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


def detect_chords(audio_path, tempo, beat_times, beats_per_measure=4, min_confidence=0.55):
    """마디 번호(1-based) -> (root_pc, quality) 딕셔너리. 화성이 불분명한 마디는 항목 자체가 없음.
    보컬/드럼이 섞여 있어도 어느 정도 버티도록 harmonic-percussive 분리 후 크로마를 계산한다."""
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
