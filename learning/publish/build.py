"""Build a static, self-hosted copy of the Pydantic AI Field Guide deck + research notes."""
import html
import json
import re
import shutil
import sys
from pathlib import Path

import markdown

SCRATCH = Path(__file__).resolve().parent.parent
DECK = SCRATCH / 'deck' / 'project'
NOTES = SCRATCH / 'notes'
OUT = Path(sys.argv[1])

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700'
         '&family=JetBrains+Mono:wght@400;600&display=swap">')
HEAD = ('<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">' + FONTS)

NOTE_TITLES = {
    '01-core': 'Core agent features',
    '02-tools-capabilities': 'Tools, toolsets, MCP & capabilities',
    '03-models-interfaces-realtime': 'Models, interfaces & realtime',
    '04-multiagent-graph-evals': 'Multi-agent, graphs, durable execution & evals',
    '05-harness': 'Pydantic AI Harness',
    '06-examples': 'Example projects & learning path',
}

SITE_CSS = """
:root{--ink:#14182B;--paper:#F6F4EF;--soft:#4A5168;--accent:#B83A1B;--line:#D8D2C4;--card:#FCFBF8;--code:#1B2033;--codefg:#E8EBF3}
@media (prefers-color-scheme: dark){:root{--ink:#ECE9E2;--paper:#11141F;--soft:#AEB4C6;--accent:#FF9470;--line:#2E3554;--card:#1A1F31}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.6 'IBM Plex Sans',Arial,sans-serif}
a{color:var(--accent)}
.wrap{max-width:960px;margin:0 auto;padding:40px 16px 80px}
.top{display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:15px;margin-bottom:24px}
.top a{text-decoration:none}
h1{font-size:2.2rem;line-height:1.15;letter-spacing:-.5px;margin:.2em 0 .4em}
h2{font-size:1.5rem;margin-top:2em;border-top:2px solid var(--line);padding-top:.8em}
h3{font-size:1.15rem;margin-top:1.6em}
code{font-family:'JetBrains Mono','Courier New',monospace;font-size:.88em;background:color-mix(in srgb,var(--line) 45%,transparent);padding:.1em .3em;border-radius:4px}
pre{background:var(--code);color:var(--codefg);padding:16px 18px;border-radius:10px;overflow-x:auto;line-height:1.45}
pre code{background:none;padding:0;font-size:14px;color:inherit}
table{border-collapse:collapse;width:100%;font-size:15px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 10px;text-align:left;vertical-align:top}
blockquote{border-left:4px solid var(--accent);margin:1em 0;padding:.2em 1em;color:var(--soft)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;margin-top:24px}
.card{display:block;background:var(--card);border:2px solid var(--line);border-radius:14px;padding:18px 20px;text-decoration:none;color:var(--ink)}
.card b{display:block;font-size:1.1rem;margin-bottom:4px}
.card span{color:var(--soft);font-size:15px}
.card.hot{border-color:var(--accent)}
.muted{color:var(--soft)}
"""

DECK_EXTRA_CSS = """
html,body{margin:0;background:#0C0F1A}
body{font-family:'IBM Plex Sans',Arial,sans-serif}
.bar{position:sticky;top:0;z-index:10;display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:10px 16px;background:#0C0F1Aee;color:#C3C9D9;font-size:15px}
.bar a{color:#FF9470;text-decoration:none}
.bar label{margin-left:auto;cursor:pointer}
.slides{max-width:1280px;margin:0 auto;padding:16px}
.slot{margin:0 0 28px}
.frame{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;border-radius:10px;box-shadow:0 8px 30px #0008}
.frame>section{position:absolute;left:0;top:0;width:1920px;height:1080px;box-sizing:border-box;overflow:hidden;transform-origin:0 0;isolation:isolate}
.frame>section *{box-sizing:border-box}
.frame>section .code,.frame>section .card,.frame>section .node{box-sizing:border-box}
.frame aside{display:none}
.notes{background:#161B2B;color:#C3C9D9;border-radius:0 0 10px 10px;padding:14px 18px;font-size:15px;line-height:1.55;margin-top:-6px}
.notes b{color:#ECE9E2}
body.hide-notes .notes{display:none}
.num{color:#8A91A8;font-size:13px;margin:0 0 6px}
x-shape,x-icon{display:block}
x-shape[kind="arrow-right"]{clip-path:polygon(0 30%,60% 30%,60% 0,100% 50%,60% 100%,60% 70%,0 70%)}
.frame table{border-collapse:collapse}
.frame th,.frame td{padding:.35em .6em;text-align:left;border-bottom:2px solid #0002}
.frame section.dark th,.frame section.dark td{border-bottom:2px solid #fff2}
.frame th{font-weight:600}
.frame h1,.frame h2,.frame h3,.frame p,.frame ul{margin-top:0}
"""

DECK_JS = """
function fit(){document.querySelectorAll('.frame').forEach(f=>{const s=f.firstElementChild;s.style.transform='scale('+(f.clientWidth/1920)+')';});}
addEventListener('resize',fit);addEventListener('load',fit);fit();
const t=document.getElementById('toggle');
try{if(localStorage.getItem('hideNotes')==='1'){document.body.classList.add('hide-notes');t.checked=false;}}catch(e){}
t.addEventListener('change',()=>{document.body.classList.toggle('hide-notes',!t.checked);try{localStorage.setItem('hideNotes',t.checked?'0':'1')}catch(e){}});
"""


def page(title: str, body: str, css_href: str) -> str:
    return (f'<!doctype html><html lang="en"><head>{HEAD}<title>{html.escape(title)}</title>'
            f'<link rel="stylesheet" href="{css_href}"></head><body>{body}</body></html>')


def build_deck() -> None:
    index = json.loads((DECK / 'deck.json').read_text())
    parts = []
    for i, sid in enumerate(index['order'], 1):
        src = (DECK / 'slides' / f'{sid}.html').read_text()
        m = re.search(r'<aside>(.*?)</aside>', src, re.S)
        notes = m.group(1).strip() if m else ''
        parts.append(
            f'<div class="slot" id="s{i}"><p class="num">Slide {i} / {len(index["order"])}</p>'
            f'<div class="frame">{src}</div>'
            + (f'<div class="notes"><b>Notes.</b> {notes}</div>' if notes else '') + '</div>')
    body = ('<div class="bar"><a href="./">← Field Guide home</a><span>Pydantic AI Field Guide · '
            f'{len(index["order"])} slides</span><label><input type="checkbox" id="toggle" checked> show notes</label></div>'
            f'<div class="slides">{"".join(parts)}</div><script>{DECK_JS}</script>')
    (OUT / 'deck.css').write_text((DECK / 'deck.css').read_text() + DECK_EXTRA_CSS)
    (OUT / 'deck.html').write_text(
        f'<!doctype html><html lang="en"><head>{HEAD}<title>Pydantic AI Field Guide · Slides</title>'
        f'<link rel="stylesheet" href="deck.css"></head><body>{body}</body></html>')


def build_notes() -> list[tuple[str, str]]:
    (OUT / 'notes').mkdir(exist_ok=True)
    made = []
    for md_path in sorted(NOTES.glob('*.md')):
        stem = md_path.stem
        text = md_path.read_text()
        body_html = markdown.markdown(text, extensions=['tables', 'fenced_code', 'sane_lists'])
        title = NOTE_TITLES.get(stem, stem)
        body = (f'<div class="wrap"><div class="top"><a href="../">← Field Guide home</a>'
                f'<a href="../deck.html">Slides</a><a href="{stem}.md" download>Download .md</a></div>'
                f'{body_html}</div>')
        (OUT / 'notes' / f'{stem}.html').write_text(page(f'{title} · Pydantic AI notes', body, '../site.css'))
        shutil.copy(md_path, OUT / 'notes' / f'{stem}.md')
        made.append((stem, title))
    return made


def build_index(notes: list[tuple[str, str]]) -> None:
    cards = ''.join(f'<a class="card" href="notes/{s}.html"><b>{html.escape(t)}</b><span>Research notes · {s}.md</span></a>'
                    for s, t in notes)
    body = ('<div class="wrap"><p class="muted">A learning kit · Pydantic AI v2.71</p>'
            '<h1>Pydantic AI Field Guide</h1>'
            '<p>Every feature of the Pydantic AI agent framework: what it is, what it looks like in code, and what '
            'you’d build with it. Built from the project’s own docs and example projects (main branch, November 2026).</p>'
            '<div class="cards"><a class="card hot" href="deck.html"><b>Slides (37)</b>'
            '<span>The full deck, with speaker notes under each slide</span></a></div>'
            '<h2>Research notes</h2><p class="muted">Per-feature detail: what, when, a verified example, gotchas and the doc path. '
            'Each ends with experiment ideas and key takeaways.</p>'
            f'<div class="cards">{cards}</div></div>')
    (OUT / 'index.html').write_text(page('Pydantic AI Field Guide', body, 'site.css'))


if __name__ == '__main__':
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / 'site.css').write_text(SITE_CSS)
    build_deck()
    build_index(build_notes())
    print('built', OUT)
