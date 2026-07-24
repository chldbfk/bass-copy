"""
Phase 0 PoC: bass.wav(Demucs로 분리된 베이스 스템)에서 torchcrepe로 음정을 추출하고,
연속된 프레임을 묶어서 노트 시퀀스(시작 시간, 길이, 음이름)로 정리한다.
"""
import sys
import numpy as np
import soundfile as sf
import torch
import torchaudio
import torchcrepe

BASS_WAV = sys.argv[1] if len(sys.argv) > 1 else "separated/htdemucs/일당백-데카당_mixed/bass.wav"
OUTPUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"
SAMPLE_RATE = 16000
HOP_LENGTH = 160  # 10ms @ 16kHz
FMIN, FMAX = 35.0, 400.0  # 베이스 기타 음역대(대략 E1~G4). 주의: torchcrepe는 fmin이 너무 낮으면
# frequency_to_bins()가 음수 인덱스를 반환해 postprocess()의 확률 마스킹(probabilities[:, :minidx])이
# 파이썬 음수 슬라이싱으로 오작동하는 버그가 있음(0.0.24 기준). 35Hz 이상으로 유지할 것.
PERIODICITY_THRESHOLD = 0.5  # 이 값보다 낮으면 소리 없음/노이즈로 간주

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def hz_to_note_name(freq):
    if freq <= 0:
        return None
    midi = 69 + 12 * torch.log2(torch.tensor(freq / 440.0))
    midi_round = int(round(midi.item()))
    octave = midi_round // 12 - 1
    name = NOTE_NAMES[midi_round % 12]
    return f"{name}{octave}", midi_round


def main():
    print(f"[1/4] 오디오 로드: {BASS_WAV}")
    data, sr = sf.read(BASS_WAV)  # data shape: (frames,) or (frames, channels)
    if data.ndim > 1:
        data = data.mean(axis=1)  # 모노 변환
    audio = torch.from_numpy(np.ascontiguousarray(data)).float().unsqueeze(0)

    if sr != SAMPLE_RATE:
        print(f"[2/4] 리샘플링: {sr}Hz -> {SAMPLE_RATE}Hz")
        resampler = torchaudio.transforms.Resample(sr, SAMPLE_RATE)
        audio = resampler(audio)

    print("[3/4] torchcrepe 피치 추출 중 (CPU, 시간이 걸릴 수 있음)...")
    pitch, periodicity = torchcrepe.predict(
        audio,
        SAMPLE_RATE,
        HOP_LENGTH,
        FMIN,
        FMAX,
        model="full",
        batch_size=256,  # 1024는 일부 환경(CPU torch 2.12)에서 즉시 access violation(0xC0000005)으로 죽음
        device="cpu",
        return_periodicity=True,
    )

    pitch = pitch.squeeze(0)
    periodicity = periodicity.squeeze(0)
    frame_time = HOP_LENGTH / SAMPLE_RATE  # 초 단위 프레임 간격

    print("[4/4] 노트 시퀀스로 정리 중...")
    notes = []  # (start_time, end_time, note_name)
    current_note = None
    current_start = None
    last_time = 0.0

    for i in range(pitch.shape[0]):
        t = i * frame_time
        conf = periodicity[i].item()
        freq = pitch[i].item()

        if conf < PERIODICITY_THRESHOLD:
            note_label = None
        else:
            result = hz_to_note_name(freq)
            note_label = result[0] if result else None

        if note_label != current_note:
            if current_note is not None:
                notes.append((current_start, t, current_note))
            current_note = note_label
            current_start = t
        last_time = t

    if current_note is not None:
        notes.append((current_start, last_time, current_note))

    # 너무 짧은(60ms 미만) 조각은 노이즈로 보고 제거
    MIN_DURATION = 0.06
    notes = [n for n in notes if (n[1] - n[0]) >= MIN_DURATION]

    print(f"\n=== 추출된 노트 시퀀스 (총 {len(notes)}개, 신뢰도 임계값={PERIODICITY_THRESHOLD}) ===")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for start, end, note in notes:
            dur = end - start
            f.write(f"{start:6.2f}s ~ {end:6.2f}s ({dur:4.2f}s)  {note}\n")
    print(f"저장 완료: {OUTPUT_PATH} ({len(notes)}개 노트)")


if __name__ == "__main__":
    sys.exit(main())
