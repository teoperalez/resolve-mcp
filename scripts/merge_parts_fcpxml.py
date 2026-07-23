"""
Merge multiple auto-editor part FCPXMLs into ONE timeline FCPXML.

For split recordings (part 1.mkv, part 2.mkv, ...) that were auto-edited
per part: concatenates the parts' spines back-to-back on one timeline,
re-numbering resource ids and shifting each part's clip offsets by the
cumulative edited duration of the earlier parts. Source `start` times are
NOT touched — each part keeps referencing its own media files.

Unlike combine_autoeditor_parts_fcpxml.py (which requires pre-concatenated
media and keeps video only), this keeps every ref (video + all audio stems)
per part and needs no media processing.

Usage:
    python merge_parts_fcpxml.py part1.fcpxml part2.fcpxml ... \
        -o MAIN.fcpxml [--name "Main Timeline"] [--den 60]
"""
import re
import sys
import argparse
from pathlib import Path

RESOURCE_RE = re.compile(r"<(format|asset|effect)\s+id=\"(r\d+)\"[\s\S]*?(?:/>|</asset>|</effect>)")
SPINE_RE = re.compile(r"<spine\b[^>]*>([\s\S]*?)</spine>")
ASSET_CLIP_RE = re.compile(r"<asset-clip\s+([^>]+?)\s*/>")
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
MARKER_RE = re.compile(r"<marker\s+[^>]*/>")


def parse_rational(s: str, den: int) -> int:
    s = (s or "0s").strip()
    if s == "0s":
        return 0
    m = re.fullmatch(r"(\d+)/(\d+)s", s)
    if m:
        return round(int(m.group(1)) * den / int(m.group(2)))
    m = re.fullmatch(r"(\d+)s", s)
    if m:
        return int(m.group(1)) * den
    raise ValueError(f"bad time {s!r}")


def fmt_rational(n: int, den: int) -> str:
    return "0s" if n == 0 else f"{n}/{den}s"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parts", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--name", default="Merged Timeline")
    ap.add_argument("--den", type=int, default=60)
    args = ap.parse_args()
    den = args.den

    all_resources: list[str] = []
    all_clips: list[str] = []
    all_markers: list[str] = []
    next_rid = 1
    tl_cursor = 0  # frames

    for part_idx, path in enumerate(args.parts, 1):
        xml = path.read_text(encoding="utf-8")

        # 1. re-number this part's resource ids
        id_map: dict[str, str] = {}

        def renumber(m: re.Match) -> str:
            nonlocal next_rid
            old = m.group(2)
            new = f"r{next_rid}"
            next_rid += 1
            id_map[old] = new
            return m.group(0).replace(f'id="{old}"', f'id="{new}"', 1)

        m_res = re.search(r"<resources>([\s\S]*?)</resources>", xml)
        if not m_res:
            raise SystemExit(f"{path}: no <resources>")
        res_body = RESOURCE_RE.sub(renumber, m_res.group(1))
        # remap format= references inside the renumbered resources
        res_body = re.sub(r'format="(r\d+)"',
                          lambda m: f'format="{id_map.get(m.group(1), m.group(1))}"',
                          res_body)
        all_resources.append(res_body.strip())

        # 2. shift this part's spine clips
        m_spine = SPINE_RE.search(xml)
        if not m_spine:
            raise SystemExit(f"{path}: no <spine>")
        part_end = 0
        part_clips = []
        for cm in ASSET_CLIP_RE.finditer(m_spine.group(1)):
            attrs = dict(ATTR_RE.findall(cm.group(1)))
            off = parse_rational(attrs.get("offset", "0s"), den)
            dur = parse_rational(attrs.get("duration", "0s"), den)
            part_end = max(part_end, off + dur)
            attrs["offset"] = fmt_rational(off + tl_cursor, den)
            attrs["ref"] = id_map.get(attrs.get("ref", ""), attrs.get("ref", ""))
            ordered = [k for k in ("name", "ref", "offset", "duration", "start",
                                   "tcFormat") if k in attrs]
            ordered += [k for k in attrs if k not in ordered]
            pairs = " ".join(f'{k}="{attrs[k]}"' for k in ordered)
            part_clips.append(f"\t\t\t\t\t\t\t\t<asset-clip {pairs} />")
        all_clips.extend(part_clips)

        # 3. shift any markers (e.g. from battle-gap/recap passes)
        for mm in MARKER_RE.finditer(xml):
            tag = mm.group(0)
            sm = re.search(r'start="([^"]+)"', tag)
            if not sm:
                continue
            shifted = fmt_rational(parse_rational(sm.group(1), den) + tl_cursor, den)
            all_markers.append(tag.replace(f'start="{sm.group(1)}"',
                                           f'start="{shifted}"', 1))

        print(f"part {part_idx} ({path.name}): {len(part_clips)} clips, "
              f"{part_end / den:.1f}s edited -> timeline @ {tl_cursor / den:.1f}s")
        tl_cursor += part_end

    total_dur = fmt_rational(tl_cursor, den)
    resources_blob = "\n\t\t".join(all_resources)
    spine_blob = "\n".join(all_clips)
    markers_blob = "".join(all_markers)
    out_xml = f"""<?xml version='1.0' encoding='utf-8'?>
<fcpxml version="1.10">
\t<resources>
\t\t{resources_blob}
\t</resources>
\t<library>
\t\t<event name="{args.name}">
\t\t\t<project name="{args.name}">
\t\t\t\t<sequence format="r1" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k" duration="{total_dur}">
\t\t\t\t\t<spine>
{spine_blob}
\t\t\t\t\t</spine>{markers_blob}
\t\t\t\t</sequence>
\t\t\t</project>
\t\t</event>
\t</library>
</fcpxml>
"""
    args.output.write_text(out_xml, encoding="utf-8")
    print(f"wrote {args.output} | {len(all_clips)} clips, "
          f"{tl_cursor / den / 60:.1f} min total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
