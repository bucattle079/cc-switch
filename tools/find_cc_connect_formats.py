from __future__ import annotations

from pathlib import Path


PATHS = [
    Path(r"C:\Users\Admin\AppData\Roaming\npm\node_modules\cc-connect\bin\cc-connect.exe"),
    Path(r"C:\Users\Admin\AppData\Roaming\npm\node_modules\cc-connect\bin\cc-connect-v1.3.2-windows-amd64.exe"),
]


def main() -> None:
    bt = chr(96)
    probes = [
        "✅",
        "❌",
        "⏳",
        "⚠️",
        f"{bt}%s{bt}",
        f"%s{bt}",
        f"{bt}{bt}{bt}\n%s\n{bt}{bt}{bt}",
        "%s\n```",
        "```\n%s",
        "exit code",
        "no output",
    ]
    for path in PATHS:
        data = path.read_bytes()
        print(path)
        for text in probes:
            needle = text.encode("utf-8")
            hits: list[int] = []
            pos = 0
            while len(hits) < 10:
                idx = data.find(needle, pos)
                if idx < 0:
                    break
                hits.append(idx)
                pos = idx + 1
            print(repr(text), hits)
            for hit in hits[:3]:
                chunk = data[max(0, hit - 100) : hit + 160]
                print("  ---", hit)
                print(chunk.decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
