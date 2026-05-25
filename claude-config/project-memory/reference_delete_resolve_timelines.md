---
name: Delete Resolve timelines via MediaPool.DeleteClips
description: The two obvious APIs (Project.DeleteTimelines, MediaPool.DeleteTimelines) don't work. The working call is MediaPool.DeleteClips with the timeline media-pool items.
type: reference
project: resolve-mcp
originSessionId: d67a4cf0-ef49-42f3-87a4-44f400894785
---
When you need to delete one or more timelines from a Resolve project (typical reason: about to re-import a corrected version of the same timeline name and don't want stale ones cluttering the project, or `apply_cuts_to_fcpxml.py` is about to recreate `(cuts: high)` / `(cuts: all)`), use this exact pattern:

```python
import DaVinciResolveScript as dvr
r = dvr.scriptapp('Resolve')
p = r.GetProjectManager().GetCurrentProject()
mp = p.GetMediaPool()

# 1. Set the current timeline to a non-target so we're not deleting the active timeline
p.SetCurrentTimeline(p.GetTimelineByIndex(1))   # or any safe timeline

# 2. Walk the media-pool tree to find timeline pool items
def find_tl_items(folder, out):
    for clip in folder.GetClipList() or []:
        if clip.GetClipProperty('Type') == 'Timeline':
            out.append(clip)
    for sub in folder.GetSubFolderList() or []:
        find_tl_items(sub, out)

root = mp.GetRootFolder()
all_tl_items = []
find_tl_items(root, all_tl_items)

# 3. Filter to the ones to delete
to_delete = [c for c in all_tl_items if '(cuts:' in c.GetName()]

# 4. Delete via MediaPool.DeleteClips (NOT DeleteTimelines)
ok = mp.DeleteClips(to_delete)
```

## What does NOT work

- **`Project.DeleteTimelines(list)`** — method doesn't exist. `TypeError: 'NoneType' object is not callable`.
- **`MediaPool.DeleteTimelines(list)`** — returns `False` silently. Does nothing.
- **`Project.DeleteTimeline(timeline)`** (singular) — method doesn't exist either.

## What does work

- **`MediaPool.DeleteClips(list_of_pool_items)`** with the timeline-typed pool items (NOT the timeline objects themselves). Returns `True`.

The pool items are different objects from the timeline objects you get via `Project.GetTimelineByIndex(i)`. You have to walk the media-pool tree and identify them by `GetClipProperty('Type') == 'Timeline'`.

## Notes

- Always set the current timeline to a non-target first. Deleting the active timeline can leave Resolve in a weird state.
- Auto-mode permission classifier may block this on first call as a destructive Resolve operation. Get explicit user consent for the specific delete before retrying.
- After delete, `Project.GetTimelineCount()` and `Project.GetTimelineByIndex` reflect the change immediately.
