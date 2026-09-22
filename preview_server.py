#!/usr/bin/env python3
"""Offline GitHub-style README preview server.

Renders README.md to HTML with GitHub-like styling and serves it in the
browser. Uses only the Python standard library, so it works with no external
packages and no network access. The page live-reloads when README.md changes,
so you can edit the file and watch the preview update.

Usage:
    python3 preview_server.py            # serves README.md on 0.0.0.0:6419
    python3 preview_server.py FILE PORT  # optional overrides
"""

import html
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_FILE = "README.md"
DEFAULT_PORT = 6419


def render_inline(text):
    """Convert inline Markdown (code, bold, italic, links, images) to HTML."""
    placeholders = []

    def stash(html_fragment):
        token = f"\x00{len(placeholders)}\x00"
        placeholders.append(html_fragment)
        return token

    # Inline code spans are protected first so their contents are not parsed.
    def code_span(match):
        return stash(f"<code>{html.escape(match.group(1))}</code>")

    text = re.sub(r"`([^`]+)`", code_span, text)

    # Escape the remaining raw text so user content cannot inject HTML.
    text = html.escape(text)

    # Images: ![alt](src)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)\)",
        lambda m: stash(
            f'<img alt="{m.group(1)}" src="{m.group(2)}" style="max-width:100%;">'
        ),
        text,
    )

    # Links: [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: stash(
            f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>'
        ),
        text,
    )

    # Bold then italic.
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", text)

    for index, fragment in enumerate(placeholders):
        text = text.replace(f"\x00{index}\x00", fragment)
    return text


def render_markdown(md):
    """Convert a Markdown document into an HTML fragment."""
    lines = md.replace("\r\n", "\n").split("\n")
    out = []
    i = 0
    n = len(lines)

    # A stack of currently open list containers: (indent, tag).
    list_stack = []

    def close_lists(min_indent=-1):
        while list_stack and list_stack[-1][0] >= min_indent:
            out.append(f"</{list_stack[-1][1]}>")
            list_stack.pop()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Fenced code blocks.
        if stripped.startswith("```"):
            close_lists()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            out.append(
                "<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>"
            )
            continue

        # Blank line ends the current paragraph/list context.
        if stripped == "":
            close_lists()
            i += 1
            continue

        # Horizontal rule.
        if re.fullmatch(r"(\*\s*){3,}|(-\s*){3,}|(_\s*){3,}", stripped):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # Headings.
        heading = re.match(r"(#{1,6})\s+(.*)", stripped)
        if heading:
            close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{render_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        # Blockquote.
        if stripped.startswith(">"):
            close_lists()
            quote = re.sub(r"^>\s?", "", stripped)
            out.append(f"<blockquote>{render_inline(quote)}</blockquote>")
            i += 1
            continue

        # List items (ordered or unordered), tracked by indentation.
        list_match = re.match(r"(\s*)([-*+]|\d+\.)\s+(.*)", line)
        if list_match:
            indent = len(list_match.group(1))
            ordered = bool(re.match(r"\d+\.", list_match.group(2)))
            tag = "ol" if ordered else "ul"
            close_lists(indent + 1)
            if not list_stack or list_stack[-1][0] < indent:
                out.append(f"<{tag}>")
                list_stack.append((indent, tag))
            out.append(f"<li>{render_inline(list_match.group(3))}</li>")
            i += 1
            continue

        # Otherwise, a paragraph (join consecutive non-blank lines).
        close_lists()
        para = [stripped]
        i += 1
        while i < n and lines[i].strip() != "" and not re.match(
            r"\s*([-*+]|\d+\.)\s+|#{1,6}\s+|>|```", lines[i]
        ):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{render_inline(' '.join(para))}</p>")

    close_lists()
    return "\n".join(out)


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>README preview</title>
<style>
  body {{
    margin: 0;
    background: #f6f8fa;
    color: #1f2328;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    line-height: 1.5;
  }}
  .container {{
    max-width: 860px;
    margin: 32px auto;
    padding: 0 16px;
  }}
  .markdown-body {{
    background: #ffffff;
    border: 1px solid #d1d9e0;
    border-radius: 6px;
    padding: 40px;
  }}
  .markdown-body h1, .markdown-body h2 {{
    border-bottom: 1px solid #d1d9e0;
    padding-bottom: 0.3em;
    margin-top: 24px;
  }}
  .markdown-body h1 {{ font-size: 2em; }}
  .markdown-body h2 {{ font-size: 1.5em; }}
  .markdown-body h3 {{ font-size: 1.25em; }}
  .markdown-body a {{ color: #0969da; text-decoration: none; }}
  .markdown-body a:hover {{ text-decoration: underline; }}
  .markdown-body code {{
    background: rgba(129,139,152,0.12);
    padding: 0.2em 0.4em;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 85%;
  }}
  .markdown-body pre {{
    background: #f6f8fa;
    padding: 16px;
    border-radius: 6px;
    overflow: auto;
  }}
  .markdown-body pre code {{ background: none; padding: 0; }}
  .markdown-body blockquote {{
    margin: 0;
    padding: 0 1em;
    color: #59636e;
    border-left: 0.25em solid #d1d9e0;
  }}
  .markdown-body hr {{ border: none; border-top: 1px solid #d1d9e0; margin: 24px 0; }}
  .badge {{
    display: inline-block;
    margin-bottom: 16px;
    font-size: 12px;
    color: #59636e;
  }}
  .badge .dot {{
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #1f883d;
    margin-right: 6px;
    vertical-align: middle;
  }}
</style>
</head>
<body>
  <div class="container">
    <div class="badge"><span class="dot"></span>Live preview of {filename} &middot; edits reload automatically</div>
    <article class="markdown-body">
{body}
    </article>
  </div>
  <script>
    let last = "{mtime}";
    setInterval(async () => {{
      try {{
        const r = await fetch("/__mtime");
        const cur = await r.text();
        if (cur !== last) location.reload();
      }} catch (e) {{}}
    }}, 1500);
  </script>
</body>
</html>
"""


class PreviewHandler(BaseHTTPRequestHandler):
    filename = DEFAULT_FILE

    def _mtime(self):
        try:
            return str(os.path.getmtime(self.filename))
        except OSError:
            return "0"

    def do_GET(self):
        if self.path == "/__mtime":
            body = self._mtime().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        try:
            with open(self.filename, "r", encoding="utf-8") as fh:
                md = fh.read()
            rendered = render_markdown(md)
        except OSError as exc:
            rendered = f"<p>Could not read {html.escape(self.filename)}: {html.escape(str(exc))}</p>"

        page = PAGE_TEMPLATE.format(
            filename=html.escape(self.filename),
            body=rendered,
            mtime=self._mtime(),
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Keep the terminal readable: log page loads, skip poll requests.
        if self.path != "/__mtime":
            sys.stderr.write(
                "%s - %s\n" % (self.address_string(), fmt % args)
            )


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
    PreviewHandler.filename = filename

    server = ThreadingHTTPServer(("0.0.0.0", port), PreviewHandler)
    print(f"README preview server running at http://0.0.0.0:{port}")
    print(f"Rendering: {filename}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping preview server.")
        server.shutdown()


if __name__ == "__main__":
    main()
