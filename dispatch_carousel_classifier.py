#!/usr/bin/env python3
"""
Dispatch a Haiku subagent to classify carousel frames.
Reads frame images from plans/frames/member-carousel/ and determines
which candidate clip first shows the Member Carousel overlay.
"""

import json
import base64
import os
from pathlib import Path
import anthropic

def load_image_as_base64(path: str) -> str:
    """Load an image file and return its base64-encoded content."""
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")

def main():
    client = anthropic.Anthropic()

    frame_dir = Path("plans/frames/member-carousel")

    # Build the prompt with all frame image content
    # The Haiku agent will receive all images and classify them

    message_content = [
        {
            "type": "text",
            "text": """You are looking for the moment a "Member Carousel" / "Member Thank You" overlay STARTS in a Pokémon gameplay video.

## What the carousel looks like

When the carousel is active, the **bottom strip** of the frame shows:
- A Pokémon sprite/artwork on the **bottom-LEFT**
- A member NAME centered in the bottom-middle (usually in bright yellow text, sometimes with an "OPHELIA" / "LAVENDAR REGARDS" / etc style)
- A gym BADGE icon on the **bottom-RIGHT** (typically a small geometric/octagonal colored badge)

The rest of the frame (top portion) still shows the regular gameplay video composition (Game Boy emulator + Crystal score overlay). The carousel is an OVERLAY added in post — it does not replace the underlying frame.

## Decision rule

You have 30 candidate pairs (numbered 0–29). For each pair i:
- `first[i]` — the first frame of clip i
- `prev_last[i]` — the last frame of the clip immediately before i (i.e., clip i-1's final frame)

Classify each as "carousel" (style present) or "no carousel" (no overlay at bottom).

Find the smallest i such that `first[i]` is "carousel":
- If `prev_last[i]` is ALSO "carousel" → the carousel actually started in the previous clip. Answer with clip i-1.
- If `prev_last[i]` is "no carousel" → the carousel started exactly at clip i. Answer with clip i.

If no candidate clip has a "carousel" first frame, answer with `chosen_v1_index: null`.

## Frame Analysis

Below are all 30 candidate frame pairs. Analyze them in order and apply the decision rule.
"""
        }
    ]

    # Add all the frame images to the message
    # Organize them by candidate index
    for i in range(30):
        first_path = frame_dir / f"cand-{i:02d}-first.jpg"
        prev_last_path = frame_dir / f"cand-{i:02d}-prev-last.jpg"

        if first_path.exists() and prev_last_path.exists():
            message_content.append({
                "type": "text",
                "text": f"\n### Candidate {i} (first frame)"
            })
            message_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": load_image_as_base64(str(first_path))
                }
            })
            message_content.append({
                "type": "text",
                "text": f"Candidate {i} (prev_last frame)"
            })
            message_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": load_image_as_base64(str(prev_last_path))
                }
            })

    message_content.append({
        "type": "text",
        "text": """
## Output

Reply with ONLY a single JSON object (no markdown fences, no extra text):

{"chosen_v1_index": <int or null>, "chosen_cand_index": <int or null>, "first_carousel_cand": <int or null>, "previous_also_carousel": <bool>, "reasoning": "1-2 sentences"}

- `chosen_v1_index` = the v1_idx of the clip that starts the carousel (see decision rule).
- `chosen_cand_index` = the candidate index in this prompt of the chosen clip (or null if it's the clip immediately before candidate 0 — i.e., prev_last[0] already had the style — in which case set chosen_cand_index=-1).
- `first_carousel_cand` = the smallest candidate index whose first frame shows the carousel.
- `previous_also_carousel` = whether prev_last[first_carousel_cand] also showed the carousel.
"""
    })

    print("[*] Dispatching Haiku subagent for carousel frame classification...")

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": message_content
            }
        ]
    )

    # Extract the JSON response
    response_text = response.content[0].text
    print(f"\n[*] Haiku response:\n{response_text}\n")

    # Parse and validate JSON
    try:
        result = json.loads(response_text)
        print(f"[✓] Parsed JSON result:")
        print(json.dumps(result, indent=2))

        # Write to the .out.md file
        out_path = Path("plans/prompts/member-carousel-Misty_Red_and_Blue_Crystal_Gym_Leader_Challenge__battle-gaps___cuts__all___edit_.out.md")
        with open(out_path, "w") as f:
            f.write(response_text)
        print(f"\n[✓] Written result to {out_path}")

    except json.JSONDecodeError as e:
        print(f"[!] Failed to parse JSON: {e}")
        print(f"Raw response: {response_text}")

if __name__ == "__main__":
    main()
