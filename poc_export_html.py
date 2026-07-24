"""
Phase 0 PoC: 파이프라인 결과(마디/박자 정렬 + 운지 최적화)를 JSON으로 뽑아내고,
그 데이터를 그대로 임베드한 단일 HTML 파일로 TAB을 시각화한다.
"""
import json
import sys

from poc_tab_render import parse_notes, filter_scale_noise, optimize_fingering, STRINGS
from poc_rhythm_quantize import detect_tempo_and_beats, quantize_notes, insert_rests
from poc_scale_analysis import estimate_key, MAJOR_SCALE_STEPS, MINOR_SCALE_STEPS, PITCH_CLASS_NAMES

STRING_LABELS = [label for label, _ in STRINGS]  # ["G", "D", "A", "E"]

HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{title} — Bass TAB</title>
<style>
:root {{
  --bg: #14181a;
  --surface: #1c2224;
  --surface-raised: #232a2c;
  --text: #ece4d3;
  --text-dim: #97a19d;
  --accent: #c9973f;
  --accent-soft: rgba(201,151,63,0.16);
  --line: #3a4245;
  --line-strong: #4d5659;
  --radius: 10px;
}}
:root[data-theme="light"] {{
  --bg: #eeece2;
  --surface: #ffffff;
  --surface-raised: #f8f6ee;
  --text: #201d16;
  --text-dim: #6b6858;
  --accent: #8a5f16;
  --accent-soft: rgba(138,95,22,0.12);
  --line: #d9d4c3;
  --line-strong: #c2bca6;
}}
@media (prefers-color-scheme: light) {{
  :root:not([data-theme="dark"]) {{
    --bg: #eeece2;
    --surface: #ffffff;
    --surface-raised: #f8f6ee;
    --text: #201d16;
    --text-dim: #6b6858;
    --accent: #8a5f16;
    --accent-soft: rgba(138,95,22,0.12);
    --line: #d9d4c3;
    --line-strong: #c2bca6;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Georgia, 'Iowan Old Style', 'Palatino Linotype', serif;
  padding: 2.5rem 1.5rem 4rem;
  transition: background 0.2s, color 0.2s;
}}
.wrap {{ max-width: 1100px; margin: 0 auto; }}

header {{
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem 2rem;
  border-bottom: 1px solid var(--line-strong);
  padding-bottom: 1.1rem;
  margin-bottom: 2rem;
}}
h1 {{
  font-size: 1.7rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  margin: 0;
  text-wrap: balance;
}}
h1 span {{ color: var(--accent); }}
.meta {{
  display: flex;
  gap: 1.4rem;
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 0.8rem;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}}
.meta b {{ color: var(--text); font-weight: 600; }}

.grid {{
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.9rem 0.7rem;
}}

.measure {{
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0.75rem 0.85rem 0.6rem;
}}
.measure-head {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.55rem;
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
}}
.measure-num {{
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  color: var(--accent);
  font-weight: 600;
}}
.measure-time {{
  font-size: 0.68rem;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}}

.tab {{
  display: flex;
  flex-direction: column;
  gap: 3px;
}}
.string-row {{
  display: flex;
  align-items: center;
  height: 22px;
  gap: 0.4rem;
}}
.string-label {{
  width: 0.9rem;
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 0.68rem;
  color: var(--text-dim);
  flex-shrink: 0;
}}
.string-track {{
  position: relative;
  flex: 1;
  height: 1px;
  background: var(--line-strong);
}}
.fret {{
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  background: var(--surface);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 0.74rem;
  font-variant-numeric: tabular-nums;
  min-width: 1.1rem;
  text-align: center;
  padding: 0 1px;
}}
.fret.open {{ color: var(--accent); font-weight: 700; }}

.durations {{
  position: relative;
  margin-top: 0.6rem;
  padding-top: 0.5rem;
  border-top: 1px dashed var(--line);
  height: 40px;
}}
.note-glyph {{
  position: absolute;
  bottom: 2px;
  transform: translateX(-50%);
  color: var(--text-dim);
}}
.note-glyph svg {{ display: block; overflow: visible; }}

footer {{
  max-width: 1100px;
  margin: 2.5rem auto 0;
  font-size: 0.72rem;
  color: var(--text-dim);
  line-height: 1.7;
  border-top: 1px solid var(--line);
  padding-top: 1rem;
}}
footer b {{ color: var(--text); }}

@media (max-width: 900px) {{
  .grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
@media (max-width: 480px) {{
  body {{ padding: 1.5rem 1rem 3rem; }}
  .grid {{ grid-template-columns: 1fr; }}
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
    <span>노트 <b>{note_count}</b></span>
  </div>
</header>
<div class="grid" id="grid"></div>
</div>
<footer>
  <div class="wrap">
    표준 4현 베이스 튜닝(<b>E1-A1-D2-G2</b>) 기준 · AI 자동 채보 PoC 결과 — 검증 전 초안입니다.<br>
    각 마디는 4/4박 기준, 노란 숫자는 개방현(0프렛)을 의미합니다.
  </div>
</footer>
<script>
const DATA = {data_json};
const STRINGS = {strings_json};

const gridEl = document.getElementById('grid');
for (const measure of DATA) {{
  const card = document.createElement('div');
  card.className = 'measure';

  const head = document.createElement('div');
  head.className = 'measure-head';
  head.innerHTML = `<span class="measure-num">MEASURE ${{measure.number}}</span>` +
                    `<span class="measure-time">${{measure.start.toFixed(1)}}s–${{measure.end.toFixed(1)}}s</span>`;
  card.appendChild(head);

  const tab = document.createElement('div');
  tab.className = 'tab';

  STRINGS.forEach((label, sIdx) => {{
    const row = document.createElement('div');
    row.className = 'string-row';
    row.innerHTML = `<span class="string-label">${{label}}</span><div class="string-track"></div>`;
    const track = row.querySelector('.string-track');
    measure.notes.forEach(n => {{
      if (n.string !== sIdx) return;
      const el = document.createElement('span');
      el.className = 'fret' + (n.fret === 0 ? ' open' : '');
      el.style.left = (n.beat / 4 * 100) + '%';
      el.textContent = n.fret;
      el.title = `${{n.name}} · ${{n.value}} · ${{n.start.toFixed(2)}}s`;
      track.appendChild(el);
    }});
    tab.appendChild(row);
  }});
  card.appendChild(tab);

  const durations = document.createElement('div');
  durations.className = 'durations';
  measure.events.forEach(e => {{
    const glyph = document.createElement('span');
    glyph.className = 'note-glyph' + (e.type === 'rest' ? ' rest' : '');
    glyph.style.left = (e.beat / 4 * 100) + '%';
    glyph.innerHTML = e.type === 'rest' ? restSymbolSVG(e.value) : noteSymbolSVG(e.value);
    glyph.title = (e.type === 'rest' ? '쉼표 · ' : '') + e.value;
    durations.appendChild(glyph);
  }});
  card.appendChild(durations);

  gridEl.appendChild(card);
}}

// 음표 라벨("점8분음표" 등)을 실제 음표 기호(머리+기둥+꼬리)의 SVG로 그린다.
function noteSymbolSVG(label) {{
  const dotted = label.startsWith('점');
  const base = dotted ? label.slice(1) : label;
  const SHAPES = {{
    '온음표':     {{ flags: 0, head: 'open',   stem: false }},
    '2분음표':    {{ flags: 0, head: 'open',   stem: true  }},
    '4분음표':    {{ flags: 0, head: 'filled', stem: true  }},
    '8분음표':    {{ flags: 1, head: 'filled', stem: true  }},
    '16분음표':   {{ flags: 2, head: 'filled', stem: true  }},
    '32분음표':   {{ flags: 3, head: 'filled', stem: true  }},
  }};
  const s = SHAPES[base] || {{ flags: 0, head: 'filled', stem: true }};

  const headCx = 7, headCy = 27, rx = 4.6, ry = 3.4;
  const stemX = headCx + rx - 0.4;
  const stemTopBase = 5;
  const stemTop = s.stem ? stemTopBase : headCy;

  let svg = '';
  // 음표머리 (온음표/2분음표는 속이 빈 타원, 4분음표 이하는 채워진 타원)
  svg += `<ellipse cx="${{headCx}}" cy="${{headCy}}" rx="${{rx}}" ry="${{ry}}" ` +
         `transform="rotate(-18 ${{headCx}} ${{headCy}})" ` +
         `fill="${{s.head === 'filled' ? 'currentColor' : 'none'}}" stroke="currentColor" stroke-width="1.1"/>`;
  // 기둥
  if (s.stem) {{
    svg += `<line x1="${{stemX}}" y1="${{headCy - 0.5}}" x2="${{stemX}}" y2="${{stemTop}}" stroke="currentColor" stroke-width="1.2"/>`;
  }}
  // 꼬리(플래그) — 개수만큼 기둥 위쪽에서 아래로 겹쳐 그림
  for (let i = 0; i < s.flags; i++) {{
    const fy = stemTop + i * 6.5;
    svg += `<path d="M ${{stemX}} ${{fy}} C ${{stemX + 7}} ${{fy + 2}}, ${{stemX + 8}} ${{fy + 7}}, ${{stemX + 1.5}} ${{fy + 10}} ` +
           `C ${{stemX + 5}} ${{fy + 6}}, ${{stemX + 4}} ${{fy + 3}}, ${{stemX}} ${{fy + 1}} Z" fill="currentColor"/>`;
  }}
  // 점음표
  if (dotted) {{
    svg += `<circle cx="${{headCx + rx + 3.5}}" cy="${{headCy}}" r="1.15" fill="currentColor"/>`;
  }}

  const width = 20;
  return `<svg width="${{width}}" height="34" viewBox="0 0 20 34">${{svg}}</svg>`;
}}

// 쉼표 라벨("점4분쉼표" 등)을 실제 쉼표 기호의 SVG로 그린다.
function restSymbolSVG(label) {{
  const dotted = label.startsWith('점');
  const base = (dotted ? label.slice(1) : label).replace('음표', '쉼표');
  const cx = 10, lineY = 16;
  let svg = '';

  if (base === '온쉼표') {{
    // 기준선 아래에 매달린 사각형
    svg += `<line x1="4" y1="${{lineY}}" x2="16" y2="${{lineY}}" stroke="currentColor" stroke-width="0.6" opacity="0.4"/>`;
    svg += `<rect x="${{cx - 4}}" y="${{lineY}}" width="8" height="3" fill="currentColor"/>`;
  }} else if (base === '2분쉼표') {{
    // 기준선 위에 얹힌 사각형
    svg += `<line x1="4" y1="${{lineY}}" x2="16" y2="${{lineY}}" stroke="currentColor" stroke-width="0.6" opacity="0.4"/>`;
    svg += `<rect x="${{cx - 4}}" y="${{lineY - 3}}" width="8" height="3" fill="currentColor"/>`;
  }} else if (base === '4분쉼표') {{
    // 지그재그(갈지자) 모양
    svg += `<path d="M ${{cx + 2}} 8 C ${{cx - 2}} 10, ${{cx + 3}} 13, ${{cx - 1}} 16 ` +
           `C ${{cx - 4}} 18, ${{cx + 2}} 20, ${{cx - 1}} 23 ` +
           `C ${{cx + 1}} 25, ${{cx - 3}} 26, ${{cx - 5}} 29" ` +
           `stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
  }} else {{
    // 8분/16분/32분쉼표: 대각선 기둥 + 꼬리(고리) n개
    const flags = base === '8분쉼표' ? 1 : base === '16분쉼표' ? 2 : 3;
    svg += `<line x1="${{cx + 3}}" y1="10" x2="${{cx - 3}}" y2="26" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>`;
    for (let i = 0; i < flags; i++) {{
      const fx = cx + 3 - i * 3.2, fy = 10 + i * 5;
      svg += `<circle cx="${{fx}}" cy="${{fy}}" r="1.7" fill="currentColor"/>`;
    }}
  }}

  if (dotted) {{
    svg += `<circle cx="${{cx + 8}}" cy="${{lineY}}" r="1.15" fill="currentColor"/>`;
  }}

  return `<svg width="20" height="34" viewBox="0 0 20 34">${{svg}}</svg>`;
}}
</script>
</body>
</html>
"""


def build_html(audio_path, notes_path, title):
    notes = parse_notes(notes_path)
    notes = filter_scale_noise(notes)

    (corr, tonic, mode), _ = estimate_key(notes)
    key_label = f"{PITCH_CLASS_NAMES[tonic]} {mode}"

    tempo, beat_times = detect_tempo_and_beats(audio_path)
    quantized = quantize_notes(notes, tempo, beat_times)

    path = optimize_fingering(notes)

    measures = {}
    quantized_by_measure = {}
    for p, q in zip(path, quantized):
        s_idx, fret = p
        measures.setdefault(q["measure"], []).append({
            "string": s_idx,
            "fret": fret,
            "beat": q["beat_in_measure"],
            "value": q["note_value"],
            "name": q["name"],
            "start": q["start"],
        })
        quantized_by_measure.setdefault(q["measure"], []).append(q)

    measure_list = []
    for m in sorted(measures.keys()):
        entries = measures[m]
        events = []
        for e in insert_rests(quantized_by_measure[m]):
            if e["type"] == "note":
                events.append({"type": "note", "beat": e["beat_in_measure"], "value": e["note_value"]})
            else:
                events.append({"type": "rest", "beat": e["beat_in_measure"], "value": e["note_value"]})

        measure_list.append({
            "number": m,
            "start": entries[0]["start"],
            "end": entries[-1]["start"],
            "notes": entries,
            "events": events,
        })

    html = HTML_TEMPLATE.format(
        title=title,
        title_html=f"{title} <span>Bass TAB</span>",
        key_label=key_label,
        tempo=tempo,
        measure_count=len(measure_list),
        note_count=len(notes),
        data_json=json.dumps(measure_list, ensure_ascii=False),
        strings_json=json.dumps(STRING_LABELS, ensure_ascii=False),
    )
    return html


def main():
    audio_path = sys.argv[1] if len(sys.argv) > 1 else "일당백-데카당_mixed.mp3"
    notes_path = sys.argv[2] if len(sys.argv) > 2 else "poc_output.txt"
    title = sys.argv[3] if len(sys.argv) > 3 else "일당백 · 데카당"
    output_path = sys.argv[4] if len(sys.argv) > 4 else "poc_tab_visual.html"

    html = build_html(audio_path, notes_path, title)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML 저장 완료: {output_path}")


if __name__ == "__main__":
    main()
