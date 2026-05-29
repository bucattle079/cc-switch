from __future__ import annotations

from pathlib import Path


ENGINE = Path(r"C:\Users\Admin\Desktop\cc-connect\core\engine.go")

OLD = '''\tvar finalMsg string
\tif exitOK {
\t\tfinalMsg = fmt.Sprintf("✅ `%s`\\n```\\n%s\\n```", cmdLabel, display)
\t} else {
'''

NEW = '''\tif exitOK && display == "(no output)" {
\t\treturn nil
\t}

\tvar finalMsg string
\tif exitOK {
\t\tfinalMsg = display
\t} else {
'''

OLD_PROGRESS = '''\tif !useUpdate {
\t\t// Platform doesn't support in-place updates — send a status message
\t\te.send(p, replyCtx, fmt.Sprintf("⏳ `%s`", cmdLabel))
\t}
'''

OLD_PROGRESS_WITH_BAD_CONST = '''\tif !useUpdate && e.display.Mode != DisplayModeQuiet {
\t\t// Platform doesn't support in-place updates — send a status message,
\t\t// unless quiet display mode is intentionally keeping WeChat clean.
\t\te.send(p, replyCtx, fmt.Sprintf("⏳ `%s`", cmdLabel))
\t}
'''

NEW_PROGRESS = '''\tif !useUpdate && e.display.Mode != "quiet" {
\t\t// Platform doesn't support in-place updates — send a status message,
\t\t// unless quiet display mode is intentionally keeping WeChat clean.
\t\te.send(p, replyCtx, fmt.Sprintf("⏳ `%s`", cmdLabel))
\t}
'''


def main() -> int:
    text = ENGINE.read_text(encoding="utf-8")
    if NEW in text:
        changed = False
    elif OLD in text:
        text = text.replace(OLD, NEW, 1)
        changed = True
    else:
        raise SystemExit("target block not found")

    if NEW_PROGRESS not in text:
        if OLD_PROGRESS_WITH_BAD_CONST in text:
            text = text.replace(OLD_PROGRESS_WITH_BAD_CONST, NEW_PROGRESS, 1)
        elif OLD_PROGRESS in text:
            text = text.replace(OLD_PROGRESS, NEW_PROGRESS, 1)
        else:
            raise SystemExit("progress target block not found")
        changed = True

    if changed:
        ENGINE.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
