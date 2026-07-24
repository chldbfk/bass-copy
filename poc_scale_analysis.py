"""
Phase 0 PoC 확장: 추출된 노트 시퀀스의 음이름 분포로 곡의 조성(key/scale)을
추정하고(Krumhansl-Schmuckler 키 추정 알고리즘), 스케일에 속하지 않는 음을
찾아서 피치 검출 오류 후보로 표시한다.
"""
import re

NOTE_TO_SEMITONE = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}
PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Krumhansl-Schmuckler 키 프로파일(경험적 가중치, C 기준)
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

# 자연 장음계 / 자연 단음계 구성음(반음 기준, 근음으로부터의 간격)
MAJOR_SCALE_STEPS = {0, 2, 4, 5, 7, 9, 11}
MINOR_SCALE_STEPS = {0, 2, 3, 5, 7, 8, 10}

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
                    "start": float(start), "end": float(end),
                    "dur": float(dur), "name": name,
                    "midi": midi, "pc": midi % 12,
                })
    return notes


def correlate(hist, profile):
    n = len(hist)
    mean_h = sum(hist) / n
    mean_p = sum(profile) / n
    num = sum((hist[i] - mean_h) * (profile[i] - mean_p) for i in range(n))
    den_h = sum((hist[i] - mean_h) ** 2 for i in range(n)) ** 0.5
    den_p = sum((profile[i] - mean_p) ** 2 for i in range(n)) ** 0.5
    if den_h == 0 or den_p == 0:
        return 0.0
    return num / (den_h * den_p)


def estimate_key(notes):
    hist = [0.0] * 12
    for n in notes:
        hist[n["pc"]] += n["dur"]

    best = None  # (correlation, tonic_pc, mode)
    for tonic in range(12):
        rotated_major = [MAJOR_PROFILE[(i - tonic) % 12] for i in range(12)]
        rotated_minor = [MINOR_PROFILE[(i - tonic) % 12] for i in range(12)]
        c_major = correlate(hist, rotated_major)
        c_minor = correlate(hist, rotated_minor)
        if best is None or c_major > best[0]:
            best = (c_major, tonic, "major")
        if c_minor > best[0]:
            best = (c_minor, tonic, "minor")
    return best, hist


def main():
    notes = parse_notes("poc_output.txt")
    (corr, tonic, mode), hist = estimate_key(notes)
    scale_steps = MAJOR_SCALE_STEPS if mode == "major" else MINOR_SCALE_STEPS
    scale_pcs = {(tonic + s) % 12 for s in scale_steps}

    print(f"추정 조성: {PITCH_CLASS_NAMES[tonic]} {mode} (상관계수 {corr:.3f})")
    print(f"스케일 구성음: {[PITCH_CLASS_NAMES[pc] for pc in sorted(scale_pcs, key=lambda p: (p - tonic) % 12)]}")
    print()
    print("음이름별 누적 길이(초) -곡에서 각 음이 쓰인 비중:")
    for pc in sorted(range(12), key=lambda p: -hist[p]):
        marker = "*" if pc in scale_pcs else " "
        print(f"  {marker} {PITCH_CLASS_NAMES[pc]:>2}: {hist[pc]:5.2f}s")

    out_of_scale = [n for n in notes if n["pc"] not in scale_pcs]
    print(f"\n=== 스케일 밖 음(피치 검출 오류 후보), 총 {len(out_of_scale)}개 ===")
    for n in out_of_scale:
        print(f"  {n['start']:6.2f}s ~ {n['end']:6.2f}s ({n['dur']:.2f}s)  {n['name']}")


if __name__ == "__main__":
    main()
