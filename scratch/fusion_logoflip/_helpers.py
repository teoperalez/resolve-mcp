"""Shared helpers: reliably find and activate the logo-flip-fusion-test timeline
and its single Fusion comp clip, regardless of what the user is currently editing.
"""
import os
import sys
import time

sys.path.insert(0, r'C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules')
import DaVinciResolveScript as dvr  # type: ignore

TEST_TIMELINE_NAME = 'logo-flip-fusion-test'

BG_PNG = r'C:\Programming\resolve-mcp\fusion_assets\logo-flip\bg.png'
LOGO_PNG = r'C:\Programming\IRLPC Hyperframes\animations\logo-flip\logo-rbypc.png'
ASSETS_DIR = r'C:\Programming\resolve-mcp\fusion_assets\logo-flip'
OUT_DIR = r'C:\Programming\resolve-mcp\fusion_out\logo-flip'
REF_DIR = r'C:\Programming\resolve-mcp\reference\logo-flip'

os.makedirs(OUT_DIR, exist_ok=True)


def connect():
    r = None
    for _ in range(6):
        r = dvr.scriptapp('Resolve')
        if r:
            break
        time.sleep(2)
    if not r:
        raise RuntimeError('Could not connect to Resolve. Is it running with Scripting->Local enabled?')
    return r


def get_test_comp():
    """Returns (resolve, project, test_timeline, clip, comp). Activates the
    test timeline if it isn't already active."""
    r = connect()
    pm = r.GetProjectManager()
    proj = pm.GetCurrentProject()

    test_tl = None
    for i in range(1, proj.GetTimelineCount() + 1):
        t = proj.GetTimelineByIndex(i)
        if t and t.GetName() == TEST_TIMELINE_NAME:
            test_tl = t
            break
    if not test_tl:
        raise RuntimeError(f'Timeline "{TEST_TIMELINE_NAME}" not found in project "{proj.GetName()}"')

    if proj.GetCurrentTimeline().GetName() != TEST_TIMELINE_NAME:
        proj.SetCurrentTimeline(test_tl)
        time.sleep(0.5)

    items = test_tl.GetItemListInTrack('video', 1) or []
    if not items:
        raise RuntimeError('No clip on V1 of the test timeline')

    fusion_clips = [c for c in items if c.GetFusionCompCount() > 0]
    if not fusion_clips:
        raise RuntimeError('No Fusion-composition clip on V1')
    clip = fusion_clips[0]
    comp = clip.GetFusionCompByIndex(1)
    if not comp:
        raise RuntimeError('Could not get Fusion comp from clip')
    return r, proj, test_tl, clip, comp


def wipe_comp(comp, keep=('MediaOut',)):
    """Remove all tools except those whose RegID is in `keep`."""
    for _, t in list(comp.GetToolList(False).items()):
        if t.GetAttrs().get('TOOLS_RegID') not in keep:
            t.Delete()


def render_frames(comp, saver, frames, name_pattern):
    """Render a list of frames via the given Saver, naming each output by pattern.

    name_pattern can include '{frame:03d}' or '{frame}' placeholders.
    Returns list of (frame, path, ok, seconds).
    """
    results = []
    for f in frames:
        out = os.path.join(OUT_DIR, name_pattern.format(frame=f))
        saver.Clip[1] = out
        t0 = time.time()
        ok = comp.Render({'Start': f, 'End': f, 'Wait': True})
        results.append((f, out, ok, time.time() - t0))
    return results


# Easings
def p2_out(t):    return 1 - (1 - t) ** 2
def p2_in(t):     return t ** 2
def p2_inout(t):  return 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2
def p3_out(t):    return 1 - (1 - t) ** 3
def p3_inout(t):  return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2
def power1_out(t): return 1 - (1 - t)
def sin_inout(t): return -((1 - 2 * t) ** 2 * 0 + 0) + 0.5 * (1 - (1 - t * 2) ** 2) if t < 0.5 else 0.5 + 0.5 * (1 - (2 * t - 1) ** 2)  # rough sin.inOut


FPS = 60.0
DURATION_FRAMES = 132
