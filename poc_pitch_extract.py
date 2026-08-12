"""
Phase 0 PoC: bass.wav(Demucs로 분리된 베이스 스템)에서 torchcrepe로 음정을 추출하고,
연속된 프레임을 묶어서 노트 시퀀스(시작 시간, 길이, 음이름)로 정리한다.

노트 경계(언제 새 음이 시작되는지)는 librosa.onset.onset_detect로 잡은 실제 타건(어택)
시점을 기준으로 삼는다 — 예전에는 "피치가 바뀌는 시점" + "periodicity가 임계값 아래로
내려가는 시점"만으로 노트를 끊었는데, 베이스처럼 어택 후 소리가 잦아드는(decay) 악기는
한 번의 타건이 프레임 중간에 periodicity가 흔들려 여러 개의 가짜 짧은 노트로 쪼개지거나,
반대로 소리가 잦아드는 꼬리 구간이 통째로 "무음"으로 버려지는 문제가 컸음
(Stand-By-Me 실측: 기존 방식은 전체 구간의 45%가 임계값 미만으로 버려졌는데, 어택 기준으로
바꾸니 커버리지가 94%로 올라감 — 2026-08-12, [[project_tab_score_app]] 메모리 참고).
"""
import sys
import numpy as np
import soundfile as sf
import librosa
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
PERIODICITY_THRESHOLD = 0.35  # 노트 구간 내에서 "이 프레임의 피치를 믿을지" 판단하는 값.
# 어택 경계는 이제 onset_detect가 잡으므로, 이 값은 각 구간 안에서 신뢰할 프레임을
# 고르는 역할만 함 — 예전(구간 경계 자체를 결정하던 시절)보다 낮춰도 안전함.
MIN_CONFIDENT_FRAC = 0.15  # 한 구간(onset~다음 onset) 안에서 이 비율 이상 프레임이
# 신뢰 가능한 피치를 줘야 "노트"로 인정. 못 미치면 타악기성 노이즈/무음 구간으로 보고 버림.

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

    pitch_np = pitch.squeeze(0).numpy()
    periodicity_np = periodicity.squeeze(0).numpy()
    frame_time = HOP_LENGTH / SAMPLE_RATE  # 초 단위 프레임 간격
    n_frames = len(pitch_np)
    total_dur = n_frames * frame_time

    print("[4/4] 어택(onset) 기준으로 노트 시퀀스 정리 중...")
    # librosa.onset.onset_detect: 에너지가 갑자기 튀는(실제 타건) 시점을 잡는다.
    # torchcrepe의 프레임별 피치 연속성/신뢰도만으로 노트 경계를 나누던 예전 방식은
    # 디케이(decay) 중간의 신뢰도 흔들림에 취약했음 — 어택 기준으로 바꾸면 한 노트가
    # 여러 조각으로 잘못 쪼개지거나, 꼬리 부분이 통째로 버려지는 문제가 크게 줄어듦.
    y, sr0 = librosa.load(BASS_WAV, sr=None, mono=True)
    onsets = list(librosa.onset.onset_detect(y=y, sr=sr0, backtrack=True, units="time", hop_length=512))
    if not onsets or onsets[0] > 0.05:
        onsets = [0.0] + onsets  # 곡이 시작하자마자 소리가 나면 onset_detect가 t=0을 못 잡으므로 보정
    onsets.append(total_dur)

    notes = []  # (start_time, end_time, note_name)
    for i in range(len(onsets) - 1):
        t0, t1 = onsets[i], onsets[i + 1]
        f0, f1 = int(t0 / frame_time), min(int(t1 / frame_time), n_frames)
        if f1 <= f0:
            continue
        seg_conf = periodicity_np[f0:f1]
        seg_pitch = pitch_np[f0:f1]
        mask = seg_conf >= PERIODICITY_THRESHOLD
        if mask.sum() < max(2, MIN_CONFIDENT_FRAC * (f1 - f0)):
            continue  # 신뢰 가능한 프레임이 부족 -> 무음/타악기성 노이즈로 보고 버림
        # 구간 안에서 신뢰 프레임들의 대표 피치(중앙값)를 노트 음높이로 삼는다 —
        # 어택 직후 순간적 피치 흔들림에 평균보다 덜 흔들림.
        midi_vals = 69 + 12 * np.log2(seg_pitch[mask] / 440.0)
        midi_round = int(round(float(np.median(midi_vals))))
        name = f"{NOTE_NAMES[midi_round % 12]}{midi_round // 12 - 1}"
        notes.append((t0, t1, name))

    # 너무 짧은(60ms 미만) 조각은 노이즈로 보고 제거
    MIN_DURATION = 0.06
    notes = [n for n in notes if (n[1] - n[0]) >= MIN_DURATION]

    print(f"\n=== 추출된 노트 시퀀스 (총 {len(notes)}개, onset {len(onsets)-1}개 중, "
          f"신뢰도 임계값={PERIODICITY_THRESHOLD}) ===")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for start, end, note in notes:
            dur = end - start
            f.write(f"{start:6.2f}s ~ {end:6.2f}s ({dur:4.2f}s)  {note}\n")
    print(f"저장 완료: {OUTPUT_PATH} ({len(notes)}개 노트)")


if __name__ == "__main__":
    sys.exit(main())
