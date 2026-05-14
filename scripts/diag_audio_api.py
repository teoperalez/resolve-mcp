"""Probe what the Resolve scripting API exposes for audio track + clip
settings, and for normalization. Print everything that might be useful so we
can design the copy/normalize workflow against reality, not assumptions."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import _resolve_env  # noqa: F401
import DaVinciResolveScript as dvr

project = dvr.scriptapp('Resolve').GetProjectManager().GetCurrentProject()
tl      = project.GetCurrentTimeline()
print(f'Project: {project.GetName()!r}')
print(f'Current timeline: {tl.GetName()!r}')

print('\n── All Timeline methods (audio-ish) ──')
methods = [m for m in dir(tl) if not m.startswith('_')]
audio_ish = [m for m in methods if any(s in m.lower()
            for s in ('track', 'audio', 'normal', 'fairlight', 'mixer',
                      'setting', 'volume', 'level', 'fader'))]
for m in sorted(audio_ish):
    print(f'  Timeline.{m}')

print('\n── All Timeline methods (full list) ──')
for m in sorted(methods):
    print(f'  Timeline.{m}')

# Probe per-track properties via GetTrackName / similar
print('\n── Per-audio-track properties ──')
n_audio = tl.GetTrackCount('audio')
print(f'Audio track count: {n_audio}')
for i in range(1, n_audio + 1):
    name = tl.GetTrackName('audio', i)
    color = None
    enabled = None
    locked = None
    sub_type = None
    try: color = tl.GetTrackColor('audio', i)
    except Exception: pass
    try: enabled = tl.GetTrackEnable('audio', i)
    except Exception: pass
    try: locked = tl.GetTrackLock('audio', i)
    except Exception: pass
    try: sub_type = tl.GetTrackSubType('audio', i)
    except Exception: pass
    print(f'  A{i}: name={name!r}  color={color!r}  enable={enabled!r}  '
          f'lock={locked!r}  subtype={sub_type!r}')

# GetSetting keys that exist
print('\n── timeline.GetSetting() for audio-related keys ──')
for key in ('timelineOutputResMatchesTimelineRes', 'timelineSampleRate',
            'audioBitDepth', 'audioCaptureNumChannels', 'audioPlayoutNumChannels',
            'numberOfAudioChannels', 'audioSettings'):
    try:
        v = tl.GetSetting(key)
        print(f'  {key!r}: {v!r}')
    except Exception as e:
        print(f'  {key!r}: error {e}')

# Audio TimelineItem methods (we already know GetProperty is empty for audio,
# but check for NormalizeAudio / similar)
print('\n── Audio TimelineItem methods (NormalizeAudio etc.) ──')
a_clips = tl.GetItemListInTrack('audio', 1) or []
if a_clips:
    item = a_clips[0]
    methods = [m for m in dir(item) if not m.startswith('_')]
    norm_ish = [m for m in methods if any(s in m.lower()
                for s in ('normal', 'volume', 'level', 'fader', 'gain',
                          'audio', 'eq', 'fairlight', 'comp', 'fade'))]
    print(f'TimelineItem audio-ish methods on {item.GetName()!r}:')
    for m in sorted(norm_ish):
        print(f'  TimelineItem.{m}')

# Try probing for a project-level NormalizeAudio
print('\n── Project methods (normalize etc.) ──')
methods = [m for m in dir(project) if not m.startswith('_')]
norm_ish = [m for m in methods if any(s in m.lower()
            for s in ('normal', 'audio', 'fairlight'))]
for m in sorted(norm_ish):
    print(f'  Project.{m}')

# MediaPoolItem audio methods
print('\n── MediaPoolItem methods (normalize etc.) ──')
pool = project.GetMediaPool()
root = pool.GetRootFolder()
clip_list = root.GetClipList() or []
if clip_list:
    mpi = clip_list[0]
    methods = [m for m in dir(mpi) if not m.startswith('_')]
    norm_ish = [m for m in methods if any(s in m.lower()
                for s in ('normal', 'audio', 'fairlight'))]
    print(f'On {mpi.GetName()!r}:')
    for m in sorted(norm_ish):
        print(f'  MediaPoolItem.{m}')
