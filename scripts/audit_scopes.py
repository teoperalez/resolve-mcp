"""
audit_scopes.py — declarative per-step scope table.

For each pipeline step, declare:

    description           — human label shown in audit reports
    creates_new_timeline  — True when the step replaces the current TL
                            (audit switches from diff mode to derived
                            expectations: clip count delta, source pool
                            preservation, sibling-TL presence)
    allowed_changes       — list of {kind, track?, where?, colors?}
                            kinds:
                              clips_added, clips_removed, clips_modified,
                              clips_shifted (start_abs/end_abs move only),
                              colors_changed, locks_changed,
                              markers_ruler_added, markers_ruler_removed,
                              markers_clip_added, markers_clip_removed
                            'track' filters to a (kind, idx) tuple
                            'colors' restricts to a marker/clip color list
    must_preserve         — list of {kind, track?, where?, colors?}
                            kinds:
                              clips     — all clips on the given track unchanged
                              markers   — all markers (ruler or clip) preserved
                                          (filtered by where/colors)
                              locks     — track lock state must not change
    derived_expectations  — extra checks for creates_new_timeline steps
                              v1_clip_count_delta_gte: int
                              preserve_source_pool: bool

The validator (audit_step.py) compares the diff against these rules and
raises a violation for any change that isn't explicitly allowed.

Global audit gates also run for every step, independent of the per-step scope:
    v1_has_a1_coverage  窶・every gameplay V1 clip must have aligned A1 audio
                         coverage. Intro/outro assets are exempt.
"""
from __future__ import annotations


# Marker colors used cross-step (must survive into downstream steps)
COLORS_BATTLE_END = ['Green']
COLORS_CARO_START = ['Magenta', 'Yellow']
COLORS_CUT_FLAGS = ['Orange', 'Yellow']
COLORS_CUT_MARKERS = ['Red']
COLORS_QA_FLAGS = ['Pink', 'Yellow', 'Lime', 'Teal', 'Brown', 'Purple', 'Mint']


SCOPES: dict = {

    # ── Step 1: battle gaps (FCPXML rewrite + new (battle-gaps) timeline) ──
    'step1_battle_gaps': {
        'description': 'Insert battle gaps via FCPXML; imports a new (battle-gaps) timeline',
        'creates_new_timeline': True,
        'derived_expectations': {
            'v1_clip_count_delta_gte': 0,
            'preserve_source_pool': True,
            'new_timeline_name_contains': '(battle-gaps)',
        },
        'allowed_changes': [],
        'must_preserve': [],
    },

    # ── Step 2: rough battle-end green markers ──
    'step2_mark_battle_ends_rough': {
        'description': 'Place Green ruler markers at battle-end estimates',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'markers_ruler_added', 'colors': ['Green']},
        ],
        'must_preserve': [
            {'kind': 'clips'},  # any track
            {'kind': 'markers', 'where': 'ruler', 'except_colors': ['Green']},
            {'kind': 'markers', 'where': 'clip_level'},
        ],
    },

    # ── Step 3: LLM-flagged cut candidates ──
    'step3_mark_cut_candidates': {
        'description': 'Color V1 clips Orange/Yellow + place Red Cut markers on mid-clip flags',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'colors_changed', 'track': ('video', 1),
             'to_colors': COLORS_CUT_FLAGS + ['']},
            {'kind': 'markers_clip_added', 'colors': COLORS_CUT_MARKERS},
        ],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers', 'where': 'ruler', 'colors': COLORS_BATTLE_END},
            {'kind': 'markers', 'where': 'clip_level', 'except_colors': COLORS_CUT_MARKERS},
        ],
    },

    # ── Step 4: apply cuts → new (cuts: all) timeline ──
    'step4_apply_cuts': {
        'description': 'Apply cut candidates via FCPXML; imports (cuts: all) and (cuts: high)',
        'creates_new_timeline': True,
        'derived_expectations': {
            'preserve_source_pool': True,
            'new_timeline_name_contains': '(cuts: all)',
            'preserve_ruler_marker_count': True,
            'preserve_clip_colors': True,
        },
        'allowed_changes': [],
        'must_preserve': [],
    },

    # ── Step 5: ripple delete short V1+A1 clips ──
    'step5_remove_short_clips': {
        'description': 'Ripple delete clips < 5 frames from V1 and A1',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_removed', 'track': ('video', 1),
             'predicate': 'dur_lt_frames', 'predicate_arg': 5},
            {'kind': 'clips_removed', 'track': ('audio', 1),
             'predicate': 'dur_lt_frames', 'predicate_arg': 5},
            {'kind': 'clips_shifted', 'track': ('video', 1)},
            {'kind': 'clips_shifted', 'track': ('audio', 1)},
            # The ripple deletes invalidate src_left/src_dur identity for
            # the next clip in some auto-editor edge cases — allow incidental
            # clips_modified entries on V1/A1.
            {'kind': 'clips_modified', 'track': ('video', 1)},
            {'kind': 'clips_modified', 'track': ('audio', 1)},
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('audio', 2)},
            {'kind': 'clips', 'track': ('audio', 3)},
            {'kind': 'clips', 'track': ('video', 2)},
        ],
    },

    # ── Step 6: import assets + build edit timeline ──
    'step6_build_edit_timeline': {
        'description': 'insert_intro_outro builds (cuts: all) (edit); intro/outro added; clips shifted right',
        'creates_new_timeline': True,
        'derived_expectations': {
            'preserve_source_pool': True,
            'new_timeline_name_contains': '(edit)',
            # The new TL should have gameplay V1 count + 1 intro + 1 outro
            'v1_clip_count_delta_gte': 0,
            # Derived timelines must keep ruler markers, shifted for any
            # timeline offset changes such as the intro prepend.
            'preserve_ruler_marker_count': True,
            'preserve_clip_colors': True,
            # A2-A5 may contain intentional music/outro assets, but must not
            # contain duplicated gameplay-source audio from the MP4 import.
            'no_duplicate_source_audio_tracks': [('audio', 2), ('audio', 3),
                                                 ('audio', 4), ('audio', 5)],
        },
        'allowed_changes': [],
        'must_preserve': [],
    },

    # ── Step 7: mark A1 gaps on the edit timeline (moved from old Step 7) ──
    'step7_mark_audio_gaps': {
        'description': 'Place Red ruler markers + clip-level markers on A1 gaps > 5f',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'markers_ruler_added', 'colors': ['Red']},
            {'kind': 'markers_clip_added', 'colors': ['Red']},
        ],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers', 'where': 'ruler', 'except_colors': ['Red']},
            {'kind': 'markers', 'where': 'clip_level', 'except_colors': ['Red']},
        ],
    },

    # ── Step 8a: re-place rough battle-end markers on edit TL ──
    'step8a_replace_battle_end_markers': {
        'description': 'Remap source-time battle ends to edit-TL frames; place Green ruler markers',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'markers_ruler_added', 'colors': ['Green']},
        ],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers', 'where': 'ruler', 'except_colors': ['Green']},
            {'kind': 'markers', 'where': 'clip_level'},
        ],
    },

    # ── Step 8b: refine battle ends (delete + replace Green markers) ──
    'step8b_refine_battle_ends': {
        'description': 'Delete old Green markers, place refined Green markers at precise transitions',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'markers_ruler_added', 'colors': ['Green']},
            {'kind': 'markers_ruler_removed', 'colors': ['Green']},
        ],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers', 'where': 'ruler', 'except_colors': ['Green']},
            {'kind': 'markers', 'where': 'clip_level'},
        ],
    },

    # ── Step 9: battle intros on V2 ──
    'step9_place_battle_intros': {
        'description': 'Place gym/rival/E4 intro graphics on V2 (video-only)',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_added',   'track': ('video', 2)},
            {'kind': 'clips_removed', 'track': ('video', 2)},  # idempotent sweep
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('video', 1)},
            {'kind': 'clips', 'track': ('audio', 1)},
            {'kind': 'markers', 'where': 'ruler', 'colors': COLORS_BATTLE_END},
            {'kind': 'markers', 'where': 'clip_level'},
            {'kind': 'battle_intros_present', 'track': ('video', 2), 'min_count': 4},
        ],
    },

    # ── Step 10: find Member Carousel Start marker ──
    'step10_find_member_carousel': {
        'description': 'Place Magenta "Member Carousel Start" marker on edit-TL ruler',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'markers_ruler_added', 'colors': COLORS_CARO_START},
        ],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers', 'where': 'ruler', 'except_colors': COLORS_CARO_START},
            {'kind': 'markers', 'where': 'clip_level'},
        ],
    },

    # ── Step 11: layout carousel — V1 collapse + V2 cropped copies ──
    'step11_layout_carousel': {
        'description': 'Copy carousel V1 clips to V2 (cropped); replace V1 with one extended clip',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_added',    'track': ('video', 2)},
            {'kind': 'clips_added',    'track': ('video', 1)},
            {'kind': 'clips_removed',  'track': ('video', 1)},
            {'kind': 'clips_modified', 'track': ('video', 1)},
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('audio', 1)},
            {'kind': 'markers', 'where': 'ruler', 'colors': COLORS_BATTLE_END},
            {'kind': 'markers', 'where': 'ruler', 'colors': COLORS_CARO_START},
            {'kind': 'markers', 'where': 'clip_level'},
        ],
    },

    # ── Step 12c: place Dual Screen Lovelife on A2 (intro DSL) ──
    'step12c_place_bgm_dsl': {
        'description': 'Place opening Dual Screen Lovelife BGM clip on A2',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_added', 'track': ('audio', 2)},
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('video', 1)},
            {'kind': 'clips', 'track': ('video', 2)},
            {'kind': 'clips', 'track': ('audio', 1)},
            {'kind': 'clips', 'track': ('audio', 3)},
            {'kind': 'markers'},  # all markers
        ],
    },

    # ── Step 12d: place battle audio on A2 (INVERTED — now BEFORE BGM chain) ──
    'step12d_place_battle_audio': {
        'description': 'Place looped battle audio (rival/gym/other themes) on A2 during each battle',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_added', 'track': ('audio', 2)},
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('video', 1)},
            {'kind': 'clips', 'track': ('video', 2)},
            {'kind': 'clips', 'track': ('audio', 1)},
            {'kind': 'clips', 'track': ('audio', 3)},
            # Critically: do not disturb the DSL clip from 12c
            {'kind': 'no_a2_clip_removed_before_first_battle'},
            {'kind': 'no_a2_overlaps'},
            {'kind': 'markers'},
        ],
    },

    # ── Step 12e: chain general BGM in the COMPLEMENT of battle A2 ranges ──
    'step12e_place_battle_bgm': {
        'description': 'Chain general BGM between-battle, deriving battle ranges from existing A2 clips',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_added', 'track': ('audio', 2)},
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('video', 1)},
            {'kind': 'clips', 'track': ('video', 2)},
            {'kind': 'clips', 'track': ('audio', 1)},
            {'kind': 'clips', 'track': ('audio', 3)},
            {'kind': 'no_a2_overlaps'},  # MUST NOT overlap existing 12c/12d clips
            {'kind': 'markers'},
        ],
    },

    # ── Step 12f: pre-render fade variants, replace A2 clips ──
    'step12f_apply_audio_fades': {
        'description': 'Replace A2 clips with pre-rendered fade variants at battle boundaries',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'clips_added',   'track': ('audio', 2)},
            {'kind': 'clips_removed', 'track': ('audio', 2)},
            {'kind': 'clips_modified','track': ('audio', 2)},
        ],
        'must_preserve': [
            {'kind': 'clips', 'track': ('video', 1)},
            {'kind': 'clips', 'track': ('video', 2)},
            {'kind': 'clips', 'track': ('audio', 1)},
            {'kind': 'clips', 'track': ('audio', 3)},
            {'kind': 'a2_total_coverage_unchanged'},  # # of frames covered ~ same
            {'kind': 'markers'},
        ],
    },

    # ── Step 13: Fairlight preset (mixer state; locks A2) ──
    'step13_apply_fairlight_preset': {
        'description': 'Apply "Standard Gameplay youtube" Fairlight preset; locks A2',
        'creates_new_timeline': False,
        'allowed_changes': [
            {'kind': 'locks_changed', 'track': ('audio', 2), 'to_value': True},
            # Some Fairlight versions also rename tracks — tolerate that
        ],
        'must_preserve': [
            {'kind': 'clips'},  # all tracks' clips untouched (mixer only)
            {'kind': 'markers'},
        ],
    },

    # ── Step 14: manual audio normalize (UI step) ──
    'step14_normalize_audio': {
        'description': 'User normalizes audio levels via Resolve UI; clip names may get -1 dB style metadata',
        'creates_new_timeline': False,
        # The normalize op shouldn't change clip counts or markers
        'allowed_changes': [
            {'kind': 'clips_modified'},  # gain values; tolerate
        ],
        'must_preserve': [
            {'kind': 'clips_count'},  # no clips added/removed
            {'kind': 'markers'},
        ],
    },

    # ── Step 15: render QA 720p (external file only) ──
    'step15_render_qa': {
        'description': 'Render QA 720p MP4 to disk; no timeline changes',
        'creates_new_timeline': False,
        'allowed_changes': [],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers'},
            {'kind': 'locks'},
        ],
    },

    # ── Step 16: render Final 4K (external file only) ──
    'step16_render_4k': {
        'description': 'Render Final 4K MP4 to disk; no timeline changes',
        'creates_new_timeline': False,
        'allowed_changes': [],
        'must_preserve': [
            {'kind': 'clips'},
            {'kind': 'markers'},
            {'kind': 'locks'},
        ],
    },
}


def get_scope(step_id: str) -> dict:
    """Return the scope for a step, or an empty permissive scope if unknown."""
    scope = SCOPES.get(step_id)
    if scope is None:
        return {
            'description': f'(no scope declared for {step_id})',
            'creates_new_timeline': False,
            'allowed_changes': [],
            'must_preserve': [],
            'unknown_step': True,
        }
    return scope
