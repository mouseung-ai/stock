"""docs/index.html + docs/demo.json → 데이터가 내장된 단일 HTML(demo.html)."""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
html = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
data = json.loads((ROOT / "docs" / "demo.json").read_text(encoding="utf-8"))
blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
html = html.replace('<link rel="manifest" href="manifest.webmanifest">\n<link rel="apple-touch-icon" href="apple-touch-icon.png">\n', "")
html = html.replace("<title>금리판</title>", f"<title>금리판 (데모)</title>\n<script>window.__DATA__={blob};</script>")
out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "demo.html"
out.write_text(html, encoding="utf-8"); print(out, len(html)//1024, "KB")
