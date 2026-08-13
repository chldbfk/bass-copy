"""
Phase 0 PoC: MusicXML을 AlphaTab(전문 악보 렌더링 라이브러리)에 넘겨 실제 표준
표기(빔, 스템)와 TAB을 함께 렌더링하는 단일 HTML 파일을 만든다.
alphaTab.min.js와 Bravura 폰트, 재생용 사운드폰트(sonivox.sf2, npm의
@coderline/alphatab 배포판에서 추출)를 전부 인라인으로 임베드해 외부 네트워크
요청 없이(Artifact CSP 안전) 동작하도록 한다.
"""
import base64
import sys

from poc_export_musicxml import build_musicxml

LIB_DIR = "alphatab_lib"

HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title} — Bass Score</title>
<style>
:root {{
  --bg: #ffffff; --surface: #ffffff; --text: #111111; --text-dim: #555555;
  --accent: #8a5f16; --line: #d9d4c3; --line-strong: #c2bca6;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: Georgia, 'Iowan Old Style', 'Palatino Linotype', serif;
  padding: 2.5rem 1.5rem 4rem;
}}
.wrap {{ max-width: 1100px; margin: 0 auto; }}
header {{
  display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between;
  gap: 0.75rem 2rem; border-bottom: 1px solid var(--line-strong);
  padding-bottom: 1.1rem; margin-bottom: 1.5rem;
}}
h1 {{ font-size: 1.7rem; font-weight: 600; margin: 0; text-wrap: balance; }}
h1 span {{ color: var(--accent); }}
.meta {{
  display: flex; gap: 1.4rem; font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 0.8rem; color: var(--text-dim); font-variant-numeric: tabular-nums;
}}
.meta b {{ color: var(--text); font-weight: 600; }}
#at-player {{
  display: flex; align-items: center; gap: 0.9rem; margin-bottom: 1rem;
  padding: 0.6rem 1rem; background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px;
}}
#at-play-btn {{
  font: inherit; font-size: 0.95rem; cursor: pointer; border: 1px solid var(--line-strong);
  background: var(--bg); color: var(--text); border-radius: 999px; width: 2.4rem; height: 2.4rem;
  display: flex; align-items: center; justify-content: center;
}}
#at-play-btn:disabled {{ opacity: 0.4; cursor: default; }}
#at-player-status {{
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace; font-size: 0.8rem; color: var(--text-dim);
}}
#at-container {{
  background: var(--surface); border: 1px solid var(--line);
  border-radius: 10px; padding: 1rem; overflow-x: auto;
}}
.at-surface {{ background: var(--surface); }}
#at-error {{
  display: none; white-space: pre-wrap; font-family: 'SF Mono', Consolas, monospace;
  font-size: 0.78rem; color: #e08a6b; background: var(--surface);
  border: 1px solid var(--line); border-radius: 10px; padding: 1rem; margin-bottom: 1rem;
}}
footer {{
  max-width: 1100px; margin: 1.5rem auto 0; font-size: 0.72rem; color: var(--text-dim);
  line-height: 1.7; border-top: 1px solid var(--line); padding-top: 1rem;
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{title_html}</h1>
  <div class="meta">
    <span>조성 <b>{key_label}</b></span>
    <span>템포 <b>{tempo:.1f} BPM</b></span>
    <span>마디 <b>{measure_count}</b></span>
  </div>
</header>
<div id="at-error"></div>
<div id="at-player">
  <button id="at-play-btn" disabled aria-label="재생">▶</button>
  <span id="at-player-status">사운드폰트 로딩 중…</span>
</div>
<div id="at-container"></div>
</div>
<footer>
  <div class="wrap">
    AlphaTab으로 렌더링한 표준 표기 + TAB 결합 악보 · AI 자동 채보 PoC 결과, 검증 전 초안입니다.
  </div>
</footer>

<script id="alphatab-lib-script">
{alphatab_js}
</script>
<script>
function showError(label, err) {{
  const box = document.getElementById('at-error');
  box.style.display = 'block';
  box.textContent += `[${{label}}] ${{err && err.stack ? err.stack : err}}\n`;
}}
window.addEventListener('error', (e) => showError('window.onerror', e.error || e.message));
window.addEventListener('unhandledrejection', (e) => showError('unhandledrejection', e.reason));

try {{
  const settings = new alphaTab.Settings();
  settings.core.useWorkers = false;   // 인라인 스크립트라 워커가 참조할 별도 파일이 없음 -> 렌더링은 메인 스레드에서
  // 오디오 재생(alphaSynth)은 구조상 Web Worker가 항상 필요함(메인 스레드 폴백 없음) ->
  // 워커가 자기 코드를 importScripts()로 불러올 URL이 필요한데, 인라인 스크립트라 실제
  // 파일 경로가 없음. 이미 페이지에 박아둔 alphaTab 라이브러리 <script> 태그의 텍스트를
  // 그대로 Blob URL로 만들어 "가짜 스크립트 파일"로 넘겨주면 워커 안에서 문제없이 로드됨.
  settings.core.scriptFile = URL.createObjectURL(
    new Blob([document.getElementById('alphatab-lib-script').textContent], {{ type: 'application/javascript' }})
  );
  settings.core.smuflFontSources = new Map([
    [alphaTab.FontFileFormat.Woff2, "data:font/woff2;base64,{bravura_b64}"]
  ]);
  settings.display.staveProfile = alphaTab.StaveProfile.Tab;
  settings.notation.rhythmMode = alphaTab.TabRhythmMode.ShowWithBars;  // ShowWithBeams는 오히려 개별 꼬리를 강제함(소스 확인)
  settings.player.enablePlayer = true;
  settings.player.enableCursor = true;
  settings.player.enableUserInteraction = true;

  // 가독성: TAB 4줄 + 음표/프렛번호 전부 검은색, 배경은 항상 흰색(테마 무관)으로 고정
  const black = new alphaTab.model.Color(0, 0, 0, 255);
  settings.display.resources.staffLineColor = black;
  settings.display.resources.barSeparatorColor = black;
  settings.display.resources.barNumberColor = black;
  settings.display.resources.mainGlyphColor = black;
  settings.display.resources.secondaryGlyphColor = black;
  settings.display.resources.scoreInfoColor = black;

  const api = new alphaTab.AlphaTabApi(document.getElementById('at-container'), settings);
  api.error.on((err) => showError('alphaTab.error', err));

  // --- 재생(사운드폰트 기반 오디오) ---
  const playBtn = document.getElementById('at-play-btn');
  const playStatus = document.getElementById('at-player-status');

  function base64ToBytes(b64) {{
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }}

  api.soundFontLoaded.on(() => {{
    playStatus.textContent = '준비 완료';
    playBtn.disabled = false;
  }});
  api.playerStateChanged.on((e) => {{
    playBtn.textContent = e.state === alphaTab.synth.PlayerState.Playing ? '⏸' : '▶';
  }});

  playBtn.addEventListener('click', () => api.playPause());

  // api.player는 scoreLoaded 이후에도 한동안 null이다가(워커가 내부적으로 비동기
  // 초기화를 마쳐야 생김) 뒤늦게 생성된다 — scoreLoaded 이벤트 자체를 기다리는 걸로는
  // 부족해서, player가 실제로 생길 때까지 짧게 폴링한 뒤 사운드폰트를 넘긴다.
  let soundFontRequested = false;
  function tryLoadSoundFontWhenReady(attemptsLeft) {{
    if (soundFontRequested) return;
    if (api.player) {{
      soundFontRequested = true;
      try {{
        api.loadSoundFont(base64ToBytes("{sonivox_b64}"), false);
      }} catch (e) {{
        playStatus.textContent = '재생 불가(사운드폰트 로딩 실패)';
        showError('soundfont', e);
      }}
      return;
    }}
    if (attemptsLeft <= 0) {{
      playStatus.textContent = '재생 불가(플레이어 초기화 실패)';
      return;
    }}
    setTimeout(() => tryLoadSoundFontWhenReady(attemptsLeft - 1), 200);
  }}
  api.scoreLoaded.on(() => tryLoadSoundFontWhenReady(50));  // 최대 10초 대기

  const xml = {musicxml_js_string};
  api.load(new TextEncoder().encode(xml));
}} catch (e) {{
  showError('sync-catch', e);
}}
</script>
</body>
</html>
"""


def main():
    audio_path = sys.argv[1] if len(sys.argv) > 1 else "일당백-데카당_mixed.mp3"
    notes_path = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"
    title = sys.argv[3] if len(sys.argv) > 3 else "일당백 · 데카당"
    output_path = sys.argv[4] if len(sys.argv) > 4 else "poc_score_alphatab.html"
    override_bpm = float(sys.argv[5]) if len(sys.argv) > 5 else None
    chord_audio_path = sys.argv[6] if len(sys.argv) > 6 else None

    xml, info = build_musicxml(notes_path, audio_path, title, override_bpm=override_bpm, chord_audio_path=chord_audio_path)

    with open(f"{LIB_DIR}/alphaTab.min.js", "r", encoding="utf-8") as f:
        alphatab_js = f.read()
    with open(f"{LIB_DIR}/Bravura.woff2", "rb") as f:
        bravura_b64 = base64.b64encode(f.read()).decode("ascii")
    with open(f"{LIB_DIR}/sonivox.sf2", "rb") as f:
        sonivox_b64 = base64.b64encode(f.read()).decode("ascii")

    import json
    html = HTML_TEMPLATE.format(
        title=title,
        title_html=f"{title} <span>Bass Score</span>",
        key_label=info["key"],
        tempo=info["tempo"],
        measure_count=info["measures"],
        alphatab_js=alphatab_js,
        bravura_b64=bravura_b64,
        sonivox_b64=sonivox_b64,
        musicxml_js_string=json.dumps(xml),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
