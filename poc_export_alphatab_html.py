"""
Phase 0 PoC: MusicXML을 AlphaTab(전문 악보 렌더링 라이브러리)에 넘겨 실제 표준
표기(빔, 스템)와 TAB을 함께 렌더링하는 단일 HTML 파일을 만든다.
alphaTab.min.js와 Bravura 폰트를 전부 인라인으로 임베드해 외부 네트워크
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
<div id="at-container"></div>
</div>
<footer>
  <div class="wrap">
    AlphaTab으로 렌더링한 표준 표기 + TAB 결합 악보 · AI 자동 채보 PoC 결과, 검증 전 초안입니다.
  </div>
</footer>

<script>
{alphatab_js}
</script>
<script>
function showError(label, err) {{
  const box = document.getElementById('at-error');
  box.style.display = 'block';
  box.textContent += `[${{label}}] ${{err && err.stack ? err.stack : err}}\n`;
}}
window.addEventListener('error', (e) => showError('window.onerror', e.error || e.message));

try {{
  const settings = new alphaTab.Settings();
  settings.core.useWorkers = false;   // 인라인 스크립트라 워커가 참조할 별도 파일이 없음 -> 메인 스레드 렌더링
  settings.core.smuflFontSources = new Map([
    [alphaTab.FontFileFormat.Woff2, "data:font/woff2;base64,{bravura_b64}"]
  ]);
  settings.display.staveProfile = alphaTab.StaveProfile.Tab;
  settings.notation.rhythmMode = alphaTab.TabRhythmMode.ShowWithBars;  // ShowWithBeams는 오히려 개별 꼬리를 강제함(소스 확인)

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
  api.renderStarted.on(() => showError('info', 'renderStarted'));
  api.scoreLoaded.on((score) => {{
    const staff = score.tracks[0]?.staves[0];
    showError('info', `scoreLoaded: tracks=${{score.tracks.length}} bars=${{staff?.bars.length}}`);
    showError('info', `staff: showTablature=${{staff?.showTablature}} showStandardNotation=${{staff?.showStandardNotation}} tuning=${{JSON.stringify(staff?.tuning)}} capo=${{staff?.capo}}`);
    const bar0 = staff?.bars[0];
    const voice0 = bar0?.voices[0];
    showError('info', `bar0 voices=${{bar0?.voices.length}} beats=${{voice0?.beats.length}}`);
    const beat0 = voice0?.beats[0];
    showError('info', `beat0 notes=${{beat0?.notes.length}} note0.fret=${{beat0?.notes[0]?.fret}} note0.string=${{beat0?.notes[0]?.string}}`);
  }});
  api.renderFinished.on(() => showError('info', 'renderFinished'));
  api.postRenderFinished.on(() => {{
    showError('info', `postRenderFinished, container children=${{document.getElementById('at-container').children.length}}`);
    showError('info', `container innerHTML length=${{document.getElementById('at-container').innerHTML.length}}`);
  }});

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

    import json
    html = HTML_TEMPLATE.format(
        title=title,
        title_html=f"{title} <span>Bass Score</span>",
        key_label=info["key"],
        tempo=info["tempo"],
        measure_count=info["measures"],
        alphatab_js=alphatab_js,
        bravura_b64=bravura_b64,
        musicxml_js_string=json.dumps(xml),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
