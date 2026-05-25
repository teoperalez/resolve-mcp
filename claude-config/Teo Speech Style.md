# Teo Speech Style — Global Reference

> **Cross-project. Reference before** (1) interpreting Teo's spoken/written
> instructions to Claude, or (2) generating any narration / TTS / script
> intended to sound like Teo on his channel (IRL Pokemon Challenges / IRLPC).
>
> Derived from analysis of:
>
> 1. Teo's full A-roll dialogue across all 12 clips (~7 minutes, ~1,800 words) in
>    `C:\Programming\IRLPC Hyperframes\projects\why-i-love-living-in-japan\markers\IRLPC Why I like Japan-sequence-script.txt`.
> 2. The five long-form post-edit videos on the `@IRLPokemonChallenges` YouTube
>    channel (~125 minutes, ~23,751 words): "My biggest YouTube lie exposed",
>    "How I Edit Gaming Videos in 2026", "The BRUTALLY HONEST Truth About
>    Working in Japan", "This Pokemon Channel Made MORE Than Expected (2026
>    Channel Update)", "I became a Permanent Resident in Japan!" — transcripts
>    cached at `C:\Programming\IRLPC Hyperframes\scratch\irlpc-channel-transcripts\`.
>
> When new A-roll transcripts become available, append findings here.

---

## 1 · Sentence-opener vocabulary

Teo overwhelmingly uses **softener / re-orienter openers** rather than declarative drops. Common patterns:

| Opener | Function | Frequency | Example |
|---|---|---|---|
| **"Now, ..."** | Soft conversational reset; "let me tell you about..." | Very high (A1, A2, A5, A10) | *"Now, in my last video about Japan, I was kind of doom and gloom..."* |
| **"And so..."** | Setting up an inferred conclusion | Medium (A8) | *"And so you might imagine that this must cost an absolute fortune..."* |
| **"And the thing is, ..."** | Pivot to a nuance or counterpoint | Medium (A11) | *"And the thing is, you might think that walkable cities like this..."* |
| **"Yeah, add on to that, that ..."** | Additive transition between beats | Medium (A7) | *"Yeah, add on to that, that the city's clean, safe..."* |
| **"So all of that is really just to say that ..."** | Summarizer / wrap-up | Used at finales (A12) | *"So all of that is really just to say that while yes, working in Japan sucks..."* |
| **"As we ..."** | Place-based scene transition | Medium (A6) | *"As we come out on the other side..."* |
| **"And here, after ..."** | Geographic / temporal punctuation | Medium (A4) | *"And here, after walking just a couple minutes from my house, I've already made it over to Matsuyama Station..."* |
| **"What's up, fam? It's Teo."** | Signature channel intro — long-form videos always open here | Channel videos (every long-form opener) | *"What's up, fam? It's Teo. Today, we're going to have a little bit of a serious one..."* |
| **"So, before we get into anything, ..."** | Pre-amble before the real content starts — sets up groundwork or housekeeping | Channel monologues | *"So, before we get into anything, I guess we should do just a little history of Teo on YouTube."* |
| **"Today, ..."** / **"Today, I want to ..."** | Statement-of-intent opener for the video itself | Channel monologues | *"Today, I want to just set the record straight."*, *"Today, we're going to find out..."* |

**Avoid** dropping into hard declaratives ("Matsuyama is a city in..."). His instinct is to invite the listener in, not announce.

---

## 2 · Hedges, fillers, and softeners (high-density)

Teo's speech is dense with conversational softeners. Match these in any TTS/narration:

| Softener | Use pattern | Examples |
|---|---|---|
| **"kind of"** | Tempering an adjective or claim | *"I was **kind of** doom and gloom"*, *"**kind of** show you"*, *"this **kind of** wide area"* |
| **"you know"** | Mid-sentence pause/connector | *"see what the random, **you know**, Japanese houses"*, *"... and **you know**, keep my family here"* |
| **"really"** | Intensifier for emphasis | *"**really** like about living here"*, *"a bit of a construction zone right now"*, *"things can go **really** bad"* |
| **"basically"** | Conversational summary | *"**Basically** if you need to travel..."*, *"... is **basically** blind"* |
| **"actually"** | Contrast-against-expectation cue | *"the food is **actually** good"*, *"what I **actually** like about living in this country"*, *"don't **actually** ever plan to move back"* |
| **"like"** | Mid-sentence comparison / filler | *"**like** for a person like me"*, *"**like** you can let your kids walk..."* |
| **"a bit of a"** | Down-toner | *"it is **a bit of a** construction zone"* |
| **"or anything"** | Open-ended trailing qualifier | *"or **anything** like that"*, *"connect over to Tokyo or Osaka or **anything**"* |
| **"sort of"** | Softer cousin of "kind of"; tempers a noun or compound phrase | *"any **sort of** like watermark"*, *"that **sort of** jutdder"*, *"any **sort of** gameplay"*, *"that **sort of** stuff"* (16 hits across the channel corpus — track at the same level as "kind of") |
| **"honestly"** | Flags genuine uncertainty or candor; common in serious or confessional moments | *"I **honestly** not sure"*, *"I **honestly** don't know"*, *"**Honestly**, I wholly support the goal of this project, but..."* |
| **"frankly"** / **"quite frankly"** | Channel-register cousin of "honestly" — used to flag a sincere or harder-edged admission, especially in the working-in-Japan / behind-the-scenes content | *"And **frankly**, I'm starting to get comments..."*, *"And **quite frankly**, I did love working with the kids, but..."*, *"**Frankly**, we would hang out together"* |
| **"I mean"** | Clarifier — restating the previous claim more precisely | *"And I don't mean toxic just like your boss is a bit of a jerk. **I mean** toxic in terms of..."*, *"**I mean**, it's crystal clear from all of this..."* |
| **"literally"** | Intensifier in the channel register (almost never appears in IRL A-roll) | *"**literally** cannot move any part of their body"*, *"**literally** nothing on it"*, *"**literally** nothing to just popping off"* |
| **"obviously"** | Flags an assumed shared premise the viewer is expected to follow | *"Now **obviously** this added a lot of stress"*, *"**Obviously**, that was already kind of a nuclear option"*, *"which **obviously** leads to a lot of stress"* |
| **"I guess"** | Soft hand-off for transitions; introduces a small move ("I guess we should...") | *"**I guess** we should do just a little history of Teo on YouTube"*, *"**I guess** this is your anti-April Fools' video"*, *"And uh with that, yeah, **I guess** I'll see you guys in the next one"* |

**Implication for interpreting Teo's instructions to Claude:** when he says *"kind of weird"* he means "a bit weird" (mild). When he says *"actually good"* he means "good, against expectation." When he says *"really"* something needs fixing, treat it as **emphatic** — not a hedge. When he says *"honestly"* or *"frankly"* before a critique, treat it as candor — the next claim is the genuine view, not a hedge.

---

## 3 · Approximate quantifiers (he prefers ranges over precision)

Teo almost never gives exact numbers in conversational dialogue. He uses approximate quantifier patterns:

| Pattern | Example |
|---|---|
| **"about N"** | *"**about** two minutes from my house"*, *"**about** an hour and a half from Tokyo"* |
| **"less than N"** | *"costs us **less than** $450 per month"* |
| **"N and a half"** | *"**12 and a half years** that I've lived in Japan"* |
| **"only like N"** | *"only **like 20** minutes away"* |
| **"a couple"** | *"a **couple** minutes"* |
| **"or so"** | *"for the past 13 years **or so**"* |
| **"the past what N years"** | *"in the past **what** 12 and a half years"* — built-in self-doubt softener |

**Implication for narration/TTS:** never write *"$450/month"* as a clean number in narration. Write *"less than four hundred fifty a month"*. Never write *"1h 25m flight"* — write *"about an hour and a half by plane"*.

**Implication for interpreting Teo:** when he gives durations, treat them as approximate. *"Make it 5 seconds"* = "roughly 5 seconds; 4.5 or 5.5 is fine."

---

## 4 · Personal first-person anchors

Teo grounds claims in personal experience and time. Constantly. Match this for any TTS in his voice:

| Anchor | Examples |
|---|---|
| **Time-on-place** | *"12 and a half years that I've lived in Japan"*, *"For the past 13 years..."*, *"never once have we had our rent raised"* |
| **"For a person like me who ..."** | *"for a person **like me** who is basically blind and cannot drive a car"*, *"for a person **like me** who grew up in the Midwest"* |
| **Family references** | *"my wife and I"*, *"my son"*, *"keep my family here"*, *"my wife's home area back in Kamigawa"* |
| **Place ownership** | *"my house"*, *"my local area"*, *"my home"*, *"on my side of the station"* |
| **Negative experience claim** | *"I've **never once** even wanted to have a car"*, *"I've **never** found such a balance ... outside of Japan"* |

**Rule:** Any narration written in Teo's voice should include at least one personal time-anchor OR "for a person like me who..." OR a family reference per ~30 seconds of speech.

---

## 5 · Sentence rhythm and structure

### Rhythm patterns

- **Long compound sentences** joined with "and", "but", commas. Teo doesn't write short marketing copy; he runs clauses together.
- **Mid-sentence self-correction or restatement** is natural and expected:
  - *"We're going to see that things open up quite... We're going to see that there's a pretty significant change in the way the town looks."* (A5)
  - *"Now so far I've walked about two minutes from my house and I've already come out on this kind of wide area here where you can already see that I'm at a local train station. In fact this is Matsuyama Station..."* (A10) — "In fact this is..." is a re-naming move.
- **Trailing "etc."** is common: *"snacks, drinks, etc."*, *"kids walking them home, kids walking home by themselves from school, etcetera"*.
- **Listing in threes** (rule of threes is unconscious): *"taxis, city buses, city trains"*, *"clean, safe, you can let your kids walk"*, *"low crime rates, decent cost of living, good health care"*.

### Post-clause asides (signature move)

After a noun, Teo often clarifies inline:

- *"a three-bedroom apartment, **a three LDK as it's called here in Japan**"* (A8)
- *"Matsuyama Station, **the main station of the prefectural capital here in Ehime Prefecture**"* (A4)
- *"my wife's home area **back in Kamigawa up near Tokyo**"* (A11)
- *"something **that I can't say for convenience stores necessarily in America**"* (A2)

**Pattern:** [main noun/claim], [comma], [as-it's-called / which-is / something-that aside]. Use this in TTS for natural-sounding context drops.

### "But..." pivots

Teo uses "But..." as his most common transition — to set up the contrast that justifies the claim:

- *"But I figured I should follow up..."* (A1)
- *"But rather than just talking about it..."* (A1)
- *"But it's a main station..."* (A3)
- *"But once we go through the station building..."* (A5)
- *"It's just working here sucks. But even that probably depends on..."* (A11)

**Rule:** when generating TTS that has a hook or counterpoint, the pivot word is almost always "but" (not "however", not "yet").

### "At the end of the day, ..." finales

In long-form channel monologues, **"at the end of the day"** is Teo's dominant **section-finale pivot** — the move from setup-and-evidence to the takeaway. 8 hits across the channel corpus, all carrying this weight:

- *"**But at the end of the day**, it worked. I managed to get a ton of views off of that."*
- *"**But then at the end of the day**, I have my master bin where I keep things like my outro..."*
- *"**At the end of the day**, you get in a lot of situations where there's simply nothing that can be done."*
- *"**At the end of the day**, I worked for a center at Ehime University providing these lessons..."*
- *"**But at the end of the day**, working under stress like this for a university without training or support..."*

**Rule:** when generating a chapter-end or section-end summary line in Teo's voice for long-form content, "at the end of the day" is the preferred connector. (For shorter A-roll segments, "So all of that is really just to say that..." stays the right choice — they're not interchangeable.)

### "The fact is / the fact that ..." claim anchors

Used 21 times across the channel corpus — a recurring move when grounding a controversial or hard-earned claim:

- *"But **the fact is** that for the past 3 years, approximately, I've been lying to my community."*
- *"...including **the fact that** I've been lying to my community."*
- *"...partially to **the fact that** my content was becoming more and more like somebody like Scott's..."*

**Pattern:** [setup] + **"But the fact is that"** / **"...the fact that..."** + [the unvarnished claim]. Pair this with the honesty register described in §7.

---

## 6 · Vocabulary preferences

### Words Teo uses naturally

- **"convenient" / "convenience"** — high-frequency. Match: *"but that doesn't mean it's inconvenient"* (his example phrase).
- **"walkable"** — used for cities.
- **"insanely"** — emphatic; *"insanely good"*, *"insanely cheap"*.
- **"rural"** — *"rural Japan"*, *"living in rural Japan"*.
- **"in this country"** — preferred over "in Japan" sometimes for variety.
- **"of course"** — softens a fact: *"and of course it's why I want to raise my son here"*.
- **"hit and miss"** — judgment phrase.
- **"rose-colored glasses"** — used metaphorically.
- **"definitely"** — assurance: *"but definitely tell me in the comments"*.

### Formal Japanese-acclimated terms (he uses the formal version)

- **"Matsuyama Station"** / **"main station"** (not just "the station")
- **"Ehime Prefecture"** (full, formal) — not just "Ehime"
- **"the prefectural capital"** (formal)
- **"convenience store"** (full, not "konbini")
- **"three LDK as it's called here in Japan"** (gives the Japanese term + translation)

### Words he avoids

- Marketing-deck adjectives: *"premium"*, *"world-class"*, *"unique"*, *"exclusive"*. Never appear.
- Hard declaratives: *"Matsuyama is..."*. He'd say *"For me, Matsuyama is..."* or *"What I like about Matsuyama is..."*.
- Bullet-point speech: he doesn't list with periods between items — he flows them with commas.

---

## 7 · Tone and audience-relationship

- **Conversational, not didactic.** He's talking to the viewer like a friend, not lecturing.
- **Self-deprecating humor.** *"on your tiny little YouTube channel"* (A8). Adds humility.
- **Honest about downsides.** *"It's just working here sucks"* (A11). Doesn't sugarcoat.
- **Acknowledges the viewer directly.** *"you can buy snacks"*, *"you can let your kids walk"*, *"tell me in the comments what you think"*.
- **Hooks at sentence ends.** *"...but you can already see..."*, *"...and we're going to see that..."* — keeps the viewer with him.
- **Owns the perspective.** *"At least that's what I really like about living here"* — explicit subjectivity, not pretending to be objective.

### Honesty / candor register (long-form post-edit channel content)

When the video is a serious-topic monologue ("My biggest YouTube lie exposed", "The BRUTALLY HONEST Truth About Working in Japan"), Teo shifts into a **confession-and-admission** register on top of the conversational baseline above:

- **Opens with the admission, not the evidence.** *"What's up, fam? It's Teo. Today, we're going to have a little bit of a serious one..."* + then *"...the fact is that for the past 3 years, approximately, I've been lying to my community."* — claim comes first; the rest of the video is justification.
- **Names the thing directly, no euphemism.** *"I've been **lying**"*, *"this **lie**"*, *"I started **lying**"* — uses the blunt noun/verb (5+10 hits in one video) rather than softening to "exaggerating" or "stretching the truth".
- **Owns blame before pivoting.** *"I just have to admit that I have been lying to you guys for the past couple years, and I hope that you can forgive me..."*
- **Layers "frankly" / "honestly" before the harder claims.** *"And **frankly**, I'm starting to get comments..."*, *"...quite **frankly**, I did love working with the kids, but..."*. These flag the next line as the genuine view.
- **"I mean toxic in terms of..."** — re-grounds an emotionally-loaded word so the viewer can't misread it as hyperbole.
- **Acknowledges the audience's likely objection up front.** *"You might be asking, how can you go full-time with such a poultry amount of income? That will be for another video. But the point is..."*

**Use this register** for narration that names a downside, admits a mistake, walks back a prior claim, or sets up an "I-was-wrong" turn. **Do not** use it for the IRL travel-blog A-roll — that stays in the lighter conversational register from §1–§5.

---

## 8 · How to use this doc

### When interpreting Teo's spoken/written directions to Claude

- **"Make it significantly larger"** — given his hedge-heavy style, "significantly" is emphatic, not hedged. Bump aggressively (1.5×+), not by 2px.
- **"That's kind of weird"** — mild. Address but don't panic-rewrite.
- **"It really isn't readable"** — emphatic. Treat as a hard requirement.
- **"Try something like X"** — "like" is filler. He's giving a CONCRETE example, not a suggestion. Match X as closely as possible.
- **"Or anything"** at the end of an instruction — leaves room for variations within the spirit of the request.
- **"About N seconds"** / **"a couple"** — approximate. Don't over-engineer to hit exact timing.
- **Trailing "etc."** — implies "and other obvious cases." Generalize.

### When writing narration/TTS for his videos

Hit at least 4 of these in any 30-second narration block:

- [ ] Time-anchored personal claim ("For the past N years..." or "I've lived..." or "for a person like me who...")
- [ ] At least one softener: "kind of", "you know", "actually", "really", "basically"
- [ ] At least one approximate quantifier ("about", "less than", "or so", "only like")
- [ ] At least one "but..." pivot
- [ ] A post-clause aside (the [noun], [as-it's-called-here-in-Japan / which-is...] pattern)
- [ ] Conversational direct-address ("you can...", "you'd be surprised...")
- [ ] Self-deprecation or downside-acknowledgment if the chapter calls for it
- [ ] Formal Japanese-acclimated naming when referring to Japanese places

### Quick template for a "Teo-voice" sentence

> [Opener: "Now, " | "And so " | "And the thing is, "] [time-anchor / personal claim with softeners], [post-clause aside]. [But-pivot to hook / consequence].

Example built from template:
> "Now, for the past 13 years or so, Matsuyama City — the prefectural capital of Ehime — has been my home. It's only about an hour and a half from Tokyo by plane, but you'd be surprised how much it's got going on."

That's three softeners ("Now," "or so", "you'd be surprised"), one time-anchor (13 years), one post-clause aside (em-dash naming clause), one approximate quantifier ("about an hour and a half"), one but-pivot, and direct audience address. Reads like him.

### When critiquing his existing scripts

Look for:

- **Over-precise quantifiers** — replace with approximations.
- **Hard declaratives** — soften with "I think", "for me", or a "you know" insertion.
- **No personal anchor** — add one.
- **No "but..." pivot if the beat needs a hook** — add it.
- **Marketing-deck vocabulary** — strike it.

---

## 9 · Pokemon gameplay videos — additional patterns

Derived from analysis of:

1. The Misty Red and Blue Crystal Gym Leader Challenge transcript (~52 min,
   ~700 Whisper segments) plus prior Brock challenge context. **In-progress
   project; pre-cuts.** Several patterns derived from this source had to be
   revised once finished-video data became available — see §9.8.
2. **Ten videos from `@RSEPokemonChallenges`** (~7 hours, ~94,258 words)
   covering the *"How many Pokemon can beat Roxanne on Minimum Battles"*
   series for Pokemon Emerald: 3 long-form episodes (Eps 17–19), the Mew
   collab video, and 6 short / mid episodes (Eps 23, 24, 27, 32, 37, 38).
   Transcripts cached at `scratch/rse-channel-transcripts/`.
3. **Twenty published, fully-edited videos from `@RBYPokemonChallenges`**
   (~24 hours, ~200K words) — a stratified sample of the 10 most-popular
   videos by view count (44K–170K) and 10 random videos (1.6K–33K). Cached at
   `C:\Programming\resolve-mcp\scratch\channel-analysis\transcripts\*.txt`.
   **This is the post-edit, viewer-facing voice for the main channel** — the
   source of truth for what survives the streamer's cut process. Where this
   corpus contradicts assumptions derived from the in-progress (#1) Misty/Brock
   work, the finished-video evidence wins. See §9.8 for findings unique to the
   finished-video format.

Pokemon gameplay videos share the bulk of Teo's IRL style (sections 1-7 above) but layer on a specific gameplay-narration register. The 10-video RSE corpus also surfaces an additional **"how-many-can-beat-X" minimum-battles series sub-register** documented in §9.7. The 20-video RBY published-channel corpus surfaces the **finished-video intro / outro / ruleset-explanation register** documented in §9.8.

### 9.1 What's the SAME as IRL content

Carries over wholesale — apply the IRL rules directly:

- **Opener vocabulary** ("Now, ...", "And so...", "And the thing is, ..."). The Misty intro literally opens with *"This is Misty. Misty is the second gym leader from Gen 1, but today I want to find out how she would have done in Pokemon Crystal."* — that's Now-style softening, "but"-pivot to hook, post-clause aside. **Caveat from RBY corpus (§9.8.1):** finished-video intros in the published RBY corpus actually open with a *cold declarative claim* about as often as a Now-softened opener (see DAL06KE73UQ *"Weedle is the weakest Pokemon that theoretically could beat gen one in a Solo challenge..."*, GX-Pk-oEOB4 *"if you've watched this channel for any period of time you'll know that..."*, HiYgk0RRGcE *"everybody knows that movesets are incredibly important..."*). The "Now," opener is the dominant in-battle / mid-video transition — not necessarily the cold-open.
- **Hedges and softeners** ("kind of", "actually", "basically", "really", "you know"). Heavy density throughout. *"the AI from gen 1 would tell her to only use her normal type tackle"*, *"she's actually a legitimately strong Pokemon"*. *"of course"* is one of the densest softeners in the gameplay register — 226 hits across the RBY corpus, and 48 hits in a single video (tr3z72duBIA). Treat it as the gameplay-register equivalent of IRL's *"obviously"* / *"basically"*.
- **Approximate quantifiers** ("about", "or so", "a couple", "like N"). Even when stat values are precise, framing is approximated: *"like 29 resets"*, *"a couple of these"*.
- **Long compound sentences** with comma-and chaining. Battle narration runs together: *"Whitney leads off with her level 18 Clefairy to go up against our level 18 Staryu, and the question is..."*
- **"But..."-pivots** as the dominant transition. *"But don't worry about any of that"*, *"But today we're going to find out..."*
- **Self-deprecation and downside acknowledgement.** *"Misty cannot beat rival number three"* — explicit failure naming.
- **Direct audience address.** *"so when I get into actual battles, I'll start slamming on X defense somewhere randomly"*.
- **Mid-sentence self-correction.** Standard everywhere, including IRL — but in gameplay it happens during fast turn-based decisions: *"this Starmie wants Bubble Beam... actually wants Surf so badly"*.

### 9.2 What's DIFFERENT from IRL content

Specific to gameplay register:

| Pattern | IRL | Pokemon gameplay |
|---|---|---|
| **Numeric precision** | Approximate ("about an hour and a half") | EXACT for stats: *"level 21 Starmie"*, *"14 HP remaining"*, *"Misty's Smart AI"*. Use real numbers in narration. The approximation hedge moves to attempt counts ("like 29 resets") rather than stats. |
| **Personal-anchor density** | Once per ~30s | Lower density — gameplay events carry the narrative, not lived experience. Personal anchors appear at intro/outro and at challenge-meta moments ("we've already done a couple of these"), not turn-by-turn. |
| **Listing register** | Soft commas ("clean, safe, walkable") | Harder enumeration of game state ("Gastly, Zubat, Bayleaf"). Still rule-of-threes when summarizing. |
| **Sentence rhythm** | Long flowing prose | Often interrupted by game-state events ("oh no," "let's go," "of course it crit"). Shorter spurts during high-action moments, longer setup blocks between battles. |
| **Place-based asides** | Heavy — Matsuyama Station, Ehime Prefecture, etc. | Replaced by Pokemon-context asides — *"Brock's Onix"*, *"Misty's ace, Starmie"*, *"the rival's Bayleaf (Chikorita's first evolution)"* — AND mechanic-explanation asides *(NEW from RBY corpus)* — *"...because in this generation for some reason they made struggle a normal type move"* (DAL06KE73UQ), *"...because the AI from gen 1 would tell her to..."*. Mechanic-explanation asides teach the viewer the rule that justifies the next strategic choice. |
| **Audience address** | "you can buy snacks" / "you can let your kids walk" | "you'll see her switch to..." / "as you can see..." / less imperative — assumes viewer is following along |

### 9.3 Pokemon-specific vocabulary

Words and phrases Teo uses naturally in gameplay narration. Match these in TTS / when interpreting:

**Battle-action verbs:**
- **"leads off with"** — opening-move framing. *"his Chikorita leads off"*, *"Misty always leads off with Staryu"*
- **"send out"** / **"switch to"** — Pokemon-swap action
- **"come out"** — same: *"Starmie has to come out second"*, *"That brings out the final Nosepass"*
- **"slap on"** / **"slam on"** — item use, casual register: *"I'll start slamming on X defense"*
- **"crush"** / **"completely destroys"** / **"completely wrecks"** — outcome-positive adjectives. Validated at 53 hits across the RSE corpus: *"the Rock Tombs completely destroy this one as well"*, *"we just saw Articuno get completely wrecked"*
- **"get destroyed"** / **"get wrecked"** / **"get smoked"** — outcome-negative adjectives. *"We get wrecked, and with that, we can eliminate another Pokemon."*
- **"take out"** — KO action: *"we take out his Pokemon"*
- **"one-shot"** / **"two-hit KO"** / **"three-hitter"** *(NEW, 78 hits in RSE corpus)* — casual KO accounting. *"If we one-shot Geodudes, then we might be able to..."*, *"this is a two-hit KO"*, *"It is a three-hitter"*. Prefers the casual phrase over "OHKO/2HKO" abbreviations, which barely appear.
- **"outspeed"** *(NEW, 7 hits in RSE corpus)* — speed-stat outcome verb. *"we might be able to still outspeed the Nosepass"*, *"we're still outspeeding the first Geodude"*.

**Game-mechanical concepts:**
- **"smart AI"** *(CORRECTED — not Crystal-specific)* — used as a universal channel term for any trainer with non-random AI in any generation. 38 hits across 11 of the 20 RBY-corpus videos, including pure Gen 1 challenges. Used to flag specific trainers (*"Misty is the first true challenge of this run... because she has smart ai"* — Bnhd-1OLFsw, *"there are only a few trainers in the entire game that use smart ai"* — Bnhd-1OLFsw, *"Mewtwo would have smart AI"* — common). Treat as core channel vocabulary, not generation-gated.
- **"bad AI"** / **"random AI"** *(NEW from RBY corpus)* — paired antonym, used to characterise trainers with no smart-AI. *"a chance to just use bad moves and make mistakes against us"* (Bnhd-1OLFsw), *"random AI ... Bruno just randomly chooses one of his moves"* (UO5UpKY7_l4).
- **"held items"** — Gen 2 mechanic
- **"X defense"** / **"X attack"** / **"X speed"** — full names, not abbreviations
- **"super effective"** / **"not very effective"** — type chart
- **"same-type"** / **"STAB"** — both used; STAB appears in strategic discussion (*"a same type move and 60 power"*)
- **"reset"** / **"attempt number X"** — re-attempt narration. *"Bugsy attempt number one"*, *"Roxanne attempt number one"*, *"rival 2 attempt number one"* (DAL06KE73UQ), *"Misty attempt number one"* (DAL06KE73UQ). Always numbered. Validated at high frequency in the RBY corpus (45 hits across 8 videos) and the RSE corpus (49 hits).
- **"hard counter"** / **"counter"** — strategy framing
- **"setup"** / **"sweep"** — strategic patterns
- **"zero DVS"** / **"max DVS"** *(NEW from RBY corpus, 27 hits across 13 videos)* — the streamer is unusually consistent about specifying DV (genetic stat) values when describing his runs, since the channel ethos is "intentionally suboptimal Pokemon". *"running on zero DVS"* (DAL06KE73UQ), *"with max tvs at level 5"* (Bnhd-1OLFsw), *"we have the same DVS as the AI opponents — that's eight in every single stat except attack which is nine"* (GX-Pk-oEOB4).
- **"minimum battles"** *(NEW core-vocabulary entry, 118 hits across 18 of the 20 RBY-corpus videos)* — the channel's central format constraint, mentioned in nearly every video. The core hook for many run titles takes the form *"Can [Pokemon] beat Pokemon [Game] on Minimum Battles..."*. Often paired with *"super minimum battles"* (CIF2ELT9XWs) when sequence-breaks are also used. **Treat this as one of the highest-priority terms to keep in cuts, never elide.**
- **"badge boost"** / **"badge boosts"** *(NEW from RBY corpus)* — Gen 1/2 stat-glitch reference. *"we don't have a badge boost in attack"* (GX-Pk-oEOB4), *"because of the badge boost glitch"* (recurring), *"because we now have all the badges"*.
- **"Gen 1 miss"** *(NEW from RBY corpus)* — the channel's name for the Gen 1 ~1/256 missed-move bug, used as a strategic concept. *"a five percent chance to miss... that's 12 times more likely than getting a gen one miss"* (Bnhd-1OLFsw), *"trying to get a gen one miss"*.
- **"solo run"** / **"solo challenge"** / **"solo running stuff"** *(NEW from RBY corpus)* — challenge-format vocabulary. The constraint: only one Pokemon may participate in actual battles. *"my first full game solo run"* (rfmbVZIlNeU), *"all the standard solo running stuff"* (CIF2ELT9XWs), *"as a Pokemon Yellow Solo Challenge"*.
- **"the entire game"** *(NEW, 51 hits across 19 of 20 RBY videos)* — the standard scope-marker for full-game runs. *"beat the entire game"* / *"beats the game"*. Use this exact phrase, not *"the whole game"* (which barely appears).
- **"crit"** / **"critical hit"** *(NEW, 129 hits in RSE corpus — one of the densest gameplay terms)* — used both as RNG-event noun and as a benchmark for what counts as lucky. *"Maybe we get a crit and just get through one of the Geodudes"*, *"We got a critical hit there that caused us to lose"*, *"that's still way more luck than a critical hit"*.
- **"damage roll"** / **"good roll"** / **"better roll"** *(NEW)* — RNG-event noun for damage variance. *"we just need to actually land hits and get good rolls"*, *"we get a better roll on the next one"*.
- **"fish for"** / **"fish for a freeze"** *(NEW)* — probability-strategy verb. *"then on the final Nosepass getting a freeze"*, *"fish for a freeze on the Nosepass"*.
- **"10% chance"** / **"that's like a 10% chance at that point"** *(NEW)* — explicit probability narration is very common in minimum-battles content because the strategy is RNG-based by definition. Always says "N percent chance" or "N percent" as the form.

**Reaction / outcome interjections** *(NEW subsection — validated at scale)*:
- **"massive"** — emotional intensifier for stats, support, slates. 88 hits / 0.93 per 1k words. *"Regirock comes in here with massive defense"*, *"a massive thank you to War Sword, supporting over in Patreon"*, *"we're coming in with a massive slate"*.
- **"crazy"** / **"absolutely crazy"** / **"just absolutely crazy"** — emphatic-reaction marker for unexpected outcomes. 36 hits. *"Just absolutely crazy how hard she is to get through"*.
- **"nice"** — small positive marker after a clutch outcome. 49 hits.
- **"no way"** — disbelief or impossibility framing. 23 hits. *"There's no way that any of the randos give us any trouble"*, *"there's just no way we were going to survive enough turns"*.
- **"let's go"** — battle-reaction yell. *"So, Roxanne attempt number one. Let's go powder snow on the first Geodude"* — note this overlaps with action-prelude usage.

**Observation- and action-prelude framings** *(NEW subsection — high-frequency gameplay rhythm)*:
- **"let's see"** *(82 hits in RSE corpus, 0.87 per 1k words)* — observation prelude before checking a move-set or how a battle plays out. *"let's see the starting move set"*, *"let's see how this rival goes first"*, *"let's see how this actually goes though"*.
- **"let's try"** *(18 hits)* — action prelude when reformulating after a failed attempt. *"Let's try this again"*, *"Let's try Deoxys defense instead"*, *"Let's try this again. Maybe Wrap does more damage"*.
- **"turns out"** / **"it turns out that..."** *(40 hits, 0.42 per 1k words)* — outcome-reveal-against-expectation framing. *"Turns out to be no issue getting through there"*, *"it turns out that all you needed to do was actually give Lugia some moves"*. Direct cousin of IRL "actually" — same logic at the sentence level.
- **"the question is"** *(26 hits, validated at scale)* — stake-setting before a battle or decision. *"the question is just the Nosepass"*, *"The question is as a dragon psychic Pokemon are we going to be able to get through this"*.

**Challenge-meta vocabulary:**
- **"this challenge"** / **"this run"** — frequent self-reference to the format
- **"as far as how many gyms she can beat"** — challenge-progress framing
- **"if she can get through X"** — challenge-conditional framing
- **"how she would have done in Pokemon Crystal"** — counterfactual framing (the core Gen 2 hook)
- **"how many Pokemon can beat Roxanne on Minimum Battles"** *(NEW)* — counterfactual framing for the Gen 3 RSE channel — note the structure: *"How many [pool] beat [opponent] on [constraint]"*. Same hook-grammar as the Gen 2 channel, different constraint.
- **"impossible"** / **"basically impossible"** / **"the question is"** — challenge tension

**Pokemon proper nouns (formal full names):**
- Always uses full Pokemon names: *"Chikorita"*, *"Bayleaf"*, *"Meganium"*, *"Magnemite"*, *"Magneton"*, *"Gastly"*, *"Haunter"*, *"Gengar"*, *"Geodude"*, *"Nosepass"*, *"Articuno"*, *"Moltres"*, *"Regirock"*, *"Lugia"*, *"Suicune"*, *"Celebi"*, *"Deoxys"*, *"Mew"*. Never abbreviates ("Mag" / "Hauter" / "Nose").
- Always uses full trainer names: *"Falkner"*, *"Bugsy"*, *"Whitney"*, *"Lt. Surge"*, *"Roxanne"*, *"Brawly"*, *"Watson"*. *"May"* (rival in RSE). Reference number when ambiguous: *"Rival 2"*, *"Rival 3"*.
- Always uses full move names: *"Rock Tomb"*, *"Rock Throw"*, *"Tackle"*, *"Harden"*, *"Bullet Seed"*, *"Powder Snow"*, *"Hypnosis"*, *"Bite"*, *"Giga Drain"*, *"Wrap"*, *"Mud Slap"*, *"Sunny Day"*, *"Toxic"*, *"Spore"*, *"Dream Eater"*. Never abbreviates ("Tomb" / "Throw" / "Tac").
- Always uses full item names: *"Oran Berry"*, *"Potion"*.

### 9.4 Cut-vs-keep guidance specific to Pokemon gameplay

These are the patterns that came out of cut-candidate analysis on the Misty video. They're THE rules to apply when deciding cuts on Pokemon gameplay. **Validated against the 20-video RBY finished-channel corpus** — confirmations and refinements noted inline.

**KEEP (do not cut):**

- **Recap narration before/after a battle.** Even when the streamer says "as we already saw" or restates a fact, this is intentional viewer-orientation. Multi-attempt battles often recap state on each new attempt. Always keep. *(CONFIRMED in finished output — recap narration is preserved heavily; e.g. DAL06KE73UQ explicitly recaps the run premise multiple times across the 90+ minute video.)*
- **Pokemon-name repetition for emphasis.** *"Brock's Onix... Brock's Onix is sitting at..."* is normal because Pokemon names are key nouns that anchor the listener. Don't treat as redundant. *(CONFIRMED — finished videos preserve trainer-and-Pokemon-name repetition extensively. Trainer names like "Brock", "Misty", "Roxanne" appear dozens of times per video, never elided.)*
- **"We won, we actually won"** / **"that worked, it actually worked"** — emphatic restatement after a hard outcome. Always keep.
- **Stat re-announcements.** *"...has 14 HP. So we're sitting at 14 HP remaining."* — sometimes a redo, sometimes intentional restatement for the viewer. Keep unless the second delivery is OBVIOUSLY a cleaner re-take with a recording-level pause between.
- **Excited yells, frustration outbursts, "let's go"s.** Battle reactions are entertainment.
- **"Attempt number N"** / **"reset N"** declarations. Informational meta — keep. *(CONFIRMED at 45 hits across 8 RBY videos — bTHSwxpPZUw alone has 8 instances. Always preserved in finished output.)*
- **Outcome narration.** *"and we get a very easy victory as we defeat our rival"* — closes the battle arc, keep even if obvious.
- **Setup narration.** *"now of course we have to switch to Starmie because..."* — explains decision, keep.
- **"And with that..."** — characteristic battle-arc closer. *"And with that, we're basically ready to move on"* / *"And with that, Misty gets a chance to show..."*. Keep both halves UNLESS one is a clear trail-off. *(CONFIRMED — 38 hits across 15 of 20 RBY videos. Often takes the form *"with that being said"*, *"with that being done"*, *"with that being out of the way"* in finished output (Bnhd-1OLFsw uses all three forms within one video).)*
- **Auto-editor-split phrases.** When a Whisper segment is split across two short clips (each carrying half the words), KEEP both. The DUP_TEXT_CLUSTER_ARTIFACT heuristic now requires cluster size ≥3 to flag — don't second-guess length-2 "duplicates".
- **Atomic numbered references — NEVER split.** *(NEW 2026-05-15.)* Phrases that name a numbered entity ALWAYS travel as a unit. Keep both halves or cut both halves — never one without the other. Any cut whose boundary lands between the entity name and its number is wrong by definition.
  - **Numbered rivals:** *"Rival 2"*, *"Rival 3"*, *"rival number two"*, *"rival number one"*, *"rival number three"*. Cutting "number two" but keeping "rival" leaves the listener with *"if she can get through rival for now though..."* — broken sentence, lost reference. Same for *"rival 2 attempt number one"*: the entire 5-word unit is one phrase.
  - **Numbered attempts/resets:** *"attempt number one"*, *"attempt number two"*, *"reset 29"*, *"attempt N"*. The number is load-bearing — cutting it strips the meta context that makes the line informative.
  - **Numbered gym order:** *"the second gym leader"*, *"gym number three"*, *"the eighth gym"*. Cut as a unit.
  - **Numbered E4 / member order:** *"Elite Four member one"*, *"the third E4 member"*. Cut as a unit.
  - **Numbered Pokemon stats by index:** *"my second Pokemon"*, *"the third one in my party"*. Cut as a unit.
  - **The same rule applies to ANY [noun] [number/numeral/ordinal] sequence**, including counts produced by Whisper as digits ("2") OR words ("two") OR ordinals ("second", "third"). When evaluating a proposed cut, check whether either edge of the cut splits a `<noun> <number>` phrase. If yes — extend the cut to include both, OR shrink it to exclude both, but NEVER stop in the middle.
  - **Why this matters:** these phrases are how Teo orients the viewer in time and sequence. They're not filler — they ARE the structural backbone of run narration. Losing one is losing the listener's anchor.
- **Rules / constraint explanations.** *(NEW from RBY corpus.)* Long passages where the streamer enumerates the run's constraints (DV settings, banned moves, level cap, allowed items, etc.) are ALWAYS preserved in finished output. The streamer pre-empts viewer "wait, but..." objections by stating rules up front. UO5UpKY7_l4 spends ~90 seconds on rules before any gameplay; GX-Pk-oEOB4 spends ~60 seconds. *"first things first let's lay down some ground rules"* (UO5UpKY7_l4) is a standard rules-block opener. **Never flag any clip inside a rules-explanation block as a cut candidate** unless it's a verbatim re-take.
- **External-source corrections / fact-check asides.** *(NEW from RBY corpus.)* The streamer regularly corrects Bulbapedia, Smogon, or community wisdom mid-stream and these stay in the cut. *"Bulbapedia is completely wrong about this"* (CIF2ELT9XWs), *"did I get any of the competitive move sets wrong tell me down below"* (GX-Pk-oEOB4). Often paired with on-screen evidence. KEEP — these are signature channel content.
- **Reset-count and time-stamp meta.** *(NEW from RBY corpus.)* The streamer maintains running counts of resets and elapsed time as part of the narrative. *"we've taken like 29 resets"*, *"we had 100 and 60 170 resets"* (rfmbVZIlNeU), *"28 minutes 46 seconds to get through Lieutenant Serge"* (DAL06KE73UQ), *"in 9 minutes and 50 seconds we were able to beat Brock"* (DAL06KE73UQ). KEEP — these are challenge-meta carrying tension.
- **Tier-list / scoring asides.** *(NEW from RBY corpus.)* When the streamer references his ranking framework — *"He is low A-tier with 100 and ... 170 resets"* (rfmbVZIlNeU), *"score on my tier list"* — these are channel-format anchors. Always keep.

**CUT (high confidence):**

- **Mic-check and pre-roll.** *"Check, check"*, *"Rolling?"*, *"Is this on?"* — always at the head, always cut.
- **Throat clears, breath bursts, mic bumps.** Empty-transcript clips < 0.7s in 3+-clip clusters. The strict cluster heuristic catches these.
- **Mis-named challenge subjects from the previous video.** *"This is Misty... she's still Brock"* — when the streamer briefly says the wrong gym leader's name (carryover from the previous video he made), then restarts. Always cut the mis-take.
- ~~**Audio-duplication overlaps.**~~ *(REVOKED 2026-05-15.)* Previously: when `!!SRC_OVERLAP_PREV` fires, cut the overlap because "the other copy still plays." This is wrong — the downstream `apply_cuts_to_fcpxml.py` operates on source-frame ranges and cuts those frames from BOTH overlapping clips, removing the words entirely. Confirmed regression: cutting the overlap at "rival number two" (Misty Red v5) removed those words from both clips, leaving *"rival for now though"*. The cut analyzer prompt now forbids SRC_OVERLAP cuts. Tolerate the brief audible duplication; the right fix is upstream in the battle-gap insertion script.
- **Failed-take re-records.** Same line delivered TWICE within ~15s with a noticeable pause / cleaner second take. Cut the first.
  - *"Starmie wants Bubble Beam"* (then immediately) → *"actually Surf so badly"* — flag the wrong-move take.
  - *"We've taken like 29 resets"* (then) → *"like 20-ish resets on this fight"* — flag the inflated-number take.
  - *"Morty would have a super effective move"* (then) → *"Morty does have super effective moves against Misty"* — flag the conditional version.

**CUT (medium confidence — narrative judgment required):**

- **Mid-sentence self-corrections** ("so X, so Y" pattern) inside a single Whisper segment. The streamer started saying X, paused briefly (no segment break), corrected to Y. Cut the X portion via mid-clip cut.
  - *"so these barriers, so these berries are..."* → cut "barriers,"
- **Trail-off + ellipsis + recovery.** *"...with this team, or does it turn out that... But today we're going to find out..."* — cut the trail-off.
- **Aborted thoughts followed by "But..."-pivot to a recovery.** Same as above; the "But" signals the recovery starting.
- **"And with that... we are..."** trail-off followed by a cleaner *"And with that, we're basically ready to move on, and..."* — cut the first.
- **Stuttered word-pairs that Whisper merged into one segment.** *"i've gotten it i've gotten it all the way down to eight HP"* — cut one copy if there's a clear word-gap to align to.

### 9.5 Pokemon-gameplay sentence-rhythm signature

A typical Misty/gameplay paragraph structure:

1. **Setup** ("Now, here against Whitney...") — Now-opener + place/opponent naming
2. **Prediction or stake-setting** ("...the question is whether Misty can actually outspeed her Clefairy")
3. **Action description** ("she's going to send out... I'm going to switch to... we use Bubble Beam, which is super effective")
4. **Outcome** ("and we get a clean victory" / "and that just doesn't go well")
5. **Reflection / transition** ("And with that, we're basically ready to move on") — explicit beat-end signal

When generating gameplay-style narration in Teo's voice, hit at least 3 of these blocks per battle arc. The "reflection / transition" beat is the most reliable hook into the next setup.

**Finished-video validation (RBY corpus):** the 5-block structure holds across the 20 finished-video corpus. Worked example from DAL06KE73UQ Brock attempt:

1. *Setup* — *"so here I'm coming into this fight with only 16 PP in Poison sting"*
2. *Stake-setting* — *"but I'm simply going to hold Auto a and just use the poison sting over and over again on this Geodude"*
3. *Action* — *"we can see it's only doing two damage per hit against us now so we will actually get through this Geodude every single time but even better yet after using up all the poison things we can struggle and easily knock that Pokemon out"*
4. *Outcome* — *"by coming in at level 10 to this fight we can actually win we gained two levels we got to level 12 in only 9 minutes and 50 seconds we were able to beat Brock"*
5. *Reflection / transition* — *"and so now the best strategy for this Pokemon I think is simply to buy a lot of potions and run through the game just healing with potions and using struggle"*

Note that block 5 in finished output often **also** sets up the NEXT battle arc (compound transition), not just closes the current one.

### 9.6 Quick template for Pokemon-gameplay sentence

> [Now-opener] [Pokemon-context: trainer + their lead Pokemon + your lead Pokemon] [softener-laden action description] [outcome verb: crush/destroy/get wrecked/take out]. [And-with-that-style transition to the next beat.]

Example built from template (Crystal challenge):
> "Now of course, here against Falkner, he's going to lead off with his level 7 Pidgey, and Misty's Staryu — being like 13 levels higher and a water type — is just going to completely destroy that Pidgey with a single Tackle. And with that, we're basically ready to move on to Bugsy."

That's a Now-opener, post-clause aside ("being like 13 levels higher and a water type"), softeners ("of course", "basically", "completely"), exact stats (level 7), challenge-meta name reference (Falkner / Bugsy / Misty's Staryu), and the signature "And with that..." closer. Reads like him in gameplay register.

### 9.7 "How many can beat X" minimum-battles series sub-register

Specific to the `@RSEPokemonChallenges` *"How many Pokemon beat Roxanne on
Minimum Battles"* series and similar tally-format gameplay challenges. This
is a **sub-register of §9** — everything from §9.1–§9.6 still applies, with
these series-specific additions on top.

#### 9.7.1 What makes the tally-series different

A "how-many" series video runs the SAME single battle (e.g. vs. Roxanne)
dozens of times across an episode, with a different Pokemon attempting each
attempt. The narrative job is to keep this format from feeling repetitive
while still cleanly tallying who won and who lost.

| Aspect | Standard challenge run (Misty / gym-leader gauntlet) | "How many can beat X" tally series (RSE Roxanne) |
|---|---|---|
| **Battles per episode** | 1–3 leader fights, lots of route grinding between | 20–40 attempts at the same fight, no route content between attempts |
| **What carries narrative tension** | "Can the run survive to the next gym?" | "Can THIS Pokemon get the win?" + "What's the running tally now?" |
| **Core hook** | *"How would Misty have done in Crystal?"* | *"How many of these N Pokemon can beat Roxanne on minimum battles?"* |
| **Per-attempt rhythm** | Long compound setup + multi-turn play-by-play | Compact: name → strategy → result → tally update |
| **Tally vocabulary** | (not used) | *"managed to beat Roxanne"*, *"we can eliminate another Pokemon"*, *"that brings us to..."*, *"118 standard Pokemon that managed to beat Roxanne"*, *"Roxanne blocked 247 Pokemon in Gen 3"* |
| **Community-meta vocabulary** | Rare | Heavy — *"member picks"*, *"the fail column"*, *"the wrap-up episode"*, Patreon-tier acknowledgements |

#### 9.7.2 The compact-attempt sentence frame

Most attempts in a tally video resolve in 3–6 sentences with this skeleton:

1. **Pokemon-name + situational setup** — *"So, Roxanne attempt number one..."*
2. **Strategy declaration** — *"Let's go powder snow on the first Geodude..."* (the **"Let's go [move] on [target]"** template is the signature move of this series)
3. **Damage / outcome description** — *"...and yeah, this is a two-hit KO. We get one shot from the first Rock Tomb."*
4. **Decision** — *"...so it means there's basically not even a point to having the Oran Berry."* or *"Let's try this again. Maybe Wrap does more damage..."*
5. **Tally update + transition** — *"With that Pokemon, www411mark2 is ready to move on in the game."* / *"we can eliminate another Pokemon"* / *"that brings us to the next..."*

Use this frame as the per-attempt TTS template. Don't try to write a full
gameplay-style §9.6 paragraph for each attempt — the format demands speed
and rhythm.

#### 9.7.3 Tally / counting vocabulary

When writing tally-update narration:

- **"managed to beat Roxanne"** — single-attempt win phrasing. *"we do manage to beat Roxanne on the first attempt"*, *"118 standard Pokemon that managed to beat Roxanne"*.
- **"blocked N Pokemon"** — gym-leader-side success tally. *"Roxanne blocked 247 Pokemon in Gen 3, which is nuts"*.
- **"we can eliminate another Pokemon"** — failure phrasing for the running list. *"We get wrecked, and with that, we can eliminate another Pokemon."*
- **"the fail column"** — visual-meta reference to the on-screen tally. *"if you look at the fail column right now, you'll notice that some of these sprites have a little exclama..."*
- **"member picks"** / **"in the wrap-up episode"** / **"reduxes"** — content-format vocabulary unique to this series. *"Members came in to save them more for the next sections"*, *"before we get into reduxes etc."*
- **"this section"** — refers to a sub-tally batch within an episode. *"we're going to predict that we're going to whittle down this set even further in the next section"*.

#### 9.7.4 Probability narration

Minimum-battles content is fundamentally an RNG-strategy game, so the
narration is dense with explicit probability framing — much more than
standard challenge run content:

- **"a 10% chance at that point"** — explicit percentage, not approximated.
- **"more luck than a critical hit"** — using crit-rate as a luck benchmark.
- **"the luck that it would take to..."** — luck-required framing.
- **"fish for a freeze"** / **"fish for a [status]"** — low-probability-target strategy.
- **"if we have to get three freezes in this or start mixing in, you know, rock tomb misses, etc."** — stacked-probability framing.

This probability-density is what makes the "how-many" sub-register feel like
**game-theory commentary** rather than pure play-by-play. Match this when
writing TTS for any minimum-battles or constraint-challenge content.

#### 9.7.5 Cut-vs-keep additions for tally-series videos

These are additive to §9.4 — they apply specifically to "how-many-can-beat-X"
content where the same battle is recorded 20+ times in a row.

**KEEP (specific to tally series):**

- **Attempt-N declarations.** *"Roxanne attempt number one"*, *"attempt number one, we go bite on the first Geodude"* — these orient the viewer to the new attempt context. Always keep.
- **Repeated strategy declarations across attempts.** Each attempt restarts the *"Let's go [move]"* opener; this is intentional series rhythm, not redundancy.
- **Tally updates after each attempt.** *"With that Pokemon, www411mark2 is ready to move on"* / *"we can eliminate another Pokemon"* — keep both the success and the elimination phrasings.
- **Repeated Pokemon names across attempts.** *"the second Geodude"*, *"the final Nosepass"* — the listener loses context fast in a 20-attempt episode; these re-anchor them.
- **Patreon / member-tier shoutouts.** *"a massive thank you to War Sword, supporting over in Patreon in the Hoenn Champion tier"* — community-meta content, always keep.

**CUT (specific to tally series):**

- **Dead-time between attempts.** When the speaker pauses to set up the next save-state or re-load between attempts, the silence/throat-clear stretch is cuttable even if mid-attempt silence isn't.
- **Doubled tally updates.** *"that's 27 down... so we're at 27 eliminations now"* — same fact, two phrasings within ~10s. Cut the weaker phrasing.
- **Failed-strategy re-records.** Same as §9.4 but applies per-attempt — if the speaker articulated a strategy plan, then a cleaner re-take of the SAME plan within 15s, cut the first take.

#### 9.7.6 Quick template for a tally-series attempt

> [Trainer + "attempt number N"] [Let's-go-style move declaration] [Damage-and-outcome line] [Tally-update + transition].

Example built from template:

> "So, Roxanne attempt number one. Let's go Bullet Seed on the first Geodude — it's a three-hitter, but we get a crit on the second hit, and that takes it down. Now of course Geodude two comes out, and we just get one-shot by the Rock Tomb. And with that, we can eliminate another Pokemon from the standard list."

That's the *"attempt number N"* opener, the *"Let's go [move] on [target]"*
strategy declaration, exact-stat damage narration (three-hitter, crit), the
*"of course"* fatalist softener, *"one-shot"* casual KO accounting,
*"and with that"* finale, and *"eliminate another Pokemon from the standard
list"* tally-update phrasing. Reads like him in minimum-battles register.

### 9.8 Patterns specific to finished published videos (RBY-channel cut-applied corpus)

These are patterns observed only in the *post-edit* finished-video format —
patterns that would not appear (or would appear very differently) in raw cut
analysis or in-progress project transcripts. Derived from the 20-video
`@RBYPokemonChallenges` finished-video corpus. Use these specifically when
generating TTS or narration for a fully-edited deliverable, or when
deciding whether a candidate cut would damage the finished-video voice.

#### 9.8.1 Cold-open hook formats

Finished videos almost never wait — they open with the hook claim in the
first one or two sentences, BEFORE any softener. Three patterns dominate:

| Pattern | Example (transcript ID + literal opening) |
|---|---|
| **Subject-first declarative** | *"Weedle is the weakest Pokemon that theoretically could beat gen one in a Solo challenge in practice however you'd have better chances of getting struck by lightning..."* (DAL06KE73UQ) |
| **"if you've watched this channel for any period of time..."** | *"if you've watched this channel for any period of time you'll know that I do basically everything the opposite of how you would..."* (GX-Pk-oEOB4) |
| **"everybody knows that..."** | *"everybody knows that movesets are incredibly important in the world of Pokemon but what would happen if..."* (HiYgk0RRGcE) |
| **"today we're going to find out..."** | *"today we're going to find out if it's possible to beat the entire game of Pokemon Yellow..."* (UO5UpKY7_l4); *"today we are going to settle which is actually the best fossil Pokemon in Generation 1..."* (CIF2ELT9XWs) |
| **"so far on rby pokemon challenges..."** *(series-recap opener)* | *"so far on rby pokemon challenges we have taken three level five runs against the elite four..."* (Bnhd-1OLFsw) |

The shared structural rule: **claim first, justification second.** Even the
"today we're going to find out" softer-feeling opener still drops the
hypothesis claim immediately. Don't write a finished-video opener that
starts with *"Now,"* or *"And so,"* — those are mid-video transitions.

#### 9.8.2 The "let's get into it" pivot (cold open → run start)

Finished videos use **"let's get into it"** (or *"let's get into this"*,
*"let's just get into this"*) as the explicit pivot from the rules-and-setup
preamble into the actual gameplay. 9 hits across 8 of 20 videos as a clean
section break, plus dozens more inline.

- *"let's test it and find out now in order to ensure an Apples to Apples comparison..."* + *"so with that let's get into this first fight against our rival"* (DAL06KE73UQ)
- *"so with that being said let's get into this folks gyarados level five no xp let's see if it's possible..."* (Bnhd-1OLFsw)
- *"let's get into it but first things first let's lay down some ground rules..."* (UO5UpKY7_l4)
- *"let's get into it and find out so as we start our challenge..."* (GX-Pk-oEOB4)

**Rule:** any TTS that fakes a finished-video intro must include this pivot
verbatim, OR a near-cousin (*"let's get straight into this"*, *"let's just
get to it"*). It is the load-bearing transition between the title-card
energy of the intro and the first battle.

#### 9.8.3 Outro template (sign-off skeleton)

Every finished video closes on a 3- to 5-beat outro. The dominant skeleton:

1. **Result-summary line** — *"so this Pokemon far too powerful and finishing the game at level 74 definitely an impressive performance"* (DAL06KE73UQ); *"oh it was painful to do it but it is possible to beat Pokemon Yellow as Bruno"* (UO5UpKY7_l4); *"that does it for Bulbasaur. He does beat the game. He is low A-tier with 100 and what was it? Like nearly 100 and 60 170 resets"* (rfmbVZIlNeU).
2. **Audience-thanks / hope-you-enjoyed line** — *"I had a lot of fun playing playing it I hope you had fun watching it thanks to everybody for hanging out with me"* (DAL06KE73UQ); *"I hope you guys enjoyed this one"* (UO5UpKY7_l4); *"hope you guys enjoyed"* (rfmbVZIlNeU).
3. **CTA — "tell me down below"** *(optional)* — *"tell me what you guys think about this"* (DAL06KE73UQ); *"tell me what you think do you have an idea for a pokemon that might be able to do it..."* (Bnhd-1OLFsw).
4. **Member / Patreon shoutouts** *(longer videos only — UO5UpKY7_l4, CIF2ELT9XWs)* — *"a massive thank you to..."* / *"in the double team tier"* / *"we got going in order of seniority..."*.
5. **Signature sign-off** — *"see you in the next [video / one]"*. Validated at 14 hits across 13 of 20 videos. Variants: *"I'll see you in the next video"* (Bnhd-1OLFsw), *"see you guys in the next video"* (UO5UpKY7_l4), *"see you in the next one"* (CIF2ELT9XWs), *"anyway that does it for this one"* + *"see you in the next"* (rfmbVZIlNeU).

The two load-bearing beats are #2 (audience-thanks) and #5 (sign-off) —
present in nearly every finished video. The other three are optional.
**Rule:** any TTS that fakes a finished-video outro must include both,
in that order.

#### 9.8.4 Rules / ruleset block (finished-video format)

Almost every "Can [X] beat [Y]" video contains a discrete **rules-block**
between the cold-open hook and the first battle. The rules block:

- Starts with a clear marker — *"first things first let's lay down some ground rules"* (UO5UpKY7_l4); *"so let's break down some rules"* (HiYgk0RRGcE); *"starting with the rules first things first"* (CIF2ELT9XWs).
- Uses **"number one... number two... finally..."** as the listing structure (93 hits across 16 of 20 videos). *"there are a couple things that I can control number one I can control the order in which I put out my Pokémon number two I can control which level up moves I learn..."* (UO5UpKY7_l4).
- Enumerates: DV settings, level cap rules, allowed/banned moves and items, optional-battle policy, reset policy, and any cartridge-mod details.
- Closes with the *"let's get into it"* pivot (§9.8.2).

**Rule:** when generating TTS for a finished-video intro, the rules block
must appear AFTER the cold-open hook and BEFORE the first battle. Do not
intersperse rules into mid-video narration — that breaks the format.

#### 9.8.5 Audience-vocative — "guys" beats "folks" in 2024+ videos

The default audience vocative in current-era videos is **"guys"** (e.g.
*"see you guys in the next video"*, *"tell me what you guys think"*). The
older corpus token **"folks"** survives in this dataset only in 2022-era
videos (Bnhd-1OLFsw 2022: 19 hits; rfmbVZIlNeU 2022: 3 hits) and is rare to
absent in 2024–2025 videos. **Rule:** use *"guys"* by default for any
finished-video TTS unless deliberately mimicking a 2022-era video.

The signature **"What's up, fam? It's Teo."** opener documented in §10
belongs to the long-form `@IRLPokemonChallenges` channel, NOT to the main
`@RBYPokemonChallenges` gameplay channel. Do NOT use *"fam"* as a vocative
in gameplay-channel TTS — it does not appear in the 20-video corpus.

#### 9.8.6 Tally-list / "score" / "tier" framing across episodes

Even outside the dedicated tally-series sub-register (§9.7), single-video
challenges often close with a tier-list / score-update beat that situates
the run in the wider channel project. Examples:

- *"He is low A-tier with 100 and ... 170 resets"* (rfmbVZIlNeU)
- *"the latest in a series of runs I've done over the past couple years where we're comparing how stats stack up to move sets"* (DAL06KE73UQ)
- *"this is the latest in..."* / *"in the next [type] video..."* — the streamer treats each video as part of a serialized project, not a one-off.

**Rule:** finished-video TTS should mention how this run fits into the
broader channel project at LEAST once — typically near the close — even if
it's just one sentence. *"this is the latest in a series of runs..."* /
*"as I always say in these solo challenges..."*

#### 9.8.7 What got DEMOTED from prior §9 assumptions

These claims from the in-progress (Misty/Brock) draft of §9 did not survive
the finished-video evidence:

- **"Smart AI is Crystal-specific"** — wrong. It's universal channel vocabulary across Gen 1 and Gen 2 (38 hits, 11 videos including pure Gen 1 challenges). Treat as core. Already corrected in §9.3.
- **"The 'Now,' opener is the dominant cold-open form for gameplay videos"** — wrong. *"Now,"* is the dominant *mid-video transition* (still very common); finished video cold-opens favor a declarative claim or a *"today we're going to..."* statement-of-intent. Already nuanced in §9.1 caveat and in §9.8.1.
- **"'Folks' is a default vocative"** — partially wrong; only in 2022-era videos. Default in current-era videos is *"guys"*. Documented in §9.8.5.
- **"Place-based asides are 'replaced by Pokemon-context asides'"** (§9.2) — true but understated. Finished videos add a third category of aside: **mechanic-explanation asides** (*"...because in this generation for some reason they made struggle a normal type move"* — DAL06KE73UQ; *"...because the ai from gen 1 would tell her to..."*). These are dense in the RBY corpus and serve to teach the viewer the mechanic that justifies a strategic choice. Treat them as a third sibling to Pokemon-context and place-based asides.

---

## 10 · Long-form post-edit channel-content register

Derived from analysis of all 5 long-form videos on the `@IRLPokemonChallenges`
channel (~125 min, ~23,751 words). These are **final post-edit videos as the
audience sees them** — not raw A-roll. The IRL-travel-blog rules (§1–§7) and
the Pokemon-gameplay rules (§9) still apply, but **long-form monologue
content adds a third register** with its own structural signature.

### 10.1 What's the SAME as IRL and gameplay content

Carries over wholesale:

- **All softeners from §2** still apply, plus the new ones added there
  ("sort of", "honestly", "frankly", "I mean", "literally", "obviously",
  "I guess"). Channel monologues are if anything **denser** in softeners than
  IRL A-roll because the speaker is alone on camera for 10–35 minutes
  straight.
- **"But..." as the dominant transition.** Same rule as everywhere else.
- **Post-clause asides** (the [main noun], [as-it's-called-here / which-is /
  something-that] pattern) — very heavy density in long-form because every
  Japanese term, every YouTube-meta term, every job-title gets glossed inline.
- **Personal time-anchors** ("for the past 13 years", "back in 2013", "when I
  first came to Japan"). Long-form videos lean on these especially heavily
  because the whole video IS a long personal story.

### 10.2 What's DIFFERENT from IRL and gameplay

| Pattern | IRL (travel) | Gameplay (Pokemon) | Long-form channel |
|---|---|---|---|
| **Opener** | "Now, ..." / "And so..." | "This is X. X is the Nth gym leader..." | **"What's up, fam? It's Teo. Today, ..."** (every long-form video) |
| **Scale of single block** | 5–30 second clip | 5–60 second battle setup | **5–35 minute unbroken monologue** |
| **Section finale move** | "So all of that is really just to say that..." | "And with that, we're basically ready to move on" | **"At the end of the day, ..."** |
| **Claim-anchor move** | Time-on-place ("12 years that I've lived in Japan") | Stat-fact ("level 21 Starmie") | **"The fact is that ..."** / **"the fact that ..."** (21 hits across the corpus) |
| **Hook to viewer** | "you can let your kids walk..." | "you'll see her switch to..." | **"You might be asking ..."** / **"You'll notice that ..."** / **"You might be worried about ..."** |
| **Audience name** | (none — implicit) | (none — implicit) | **"fam"** / **"you guys"** — channel-affectionate naming |
| **Self-deprecation** | "on your tiny little YouTube channel" | "Misty cannot beat rival number three" | **Heavy** — explicit admissions ("I've been lying to my community", "this lie that I've been telling") |
| **Channel-meta references** | Rare | Rare | **Dense** — "youtube", "channel", "video", "viewers", "comments", "algorithm", "monetization" all appear several times per video |
| **Visual-callout cue** | "as you can see..." | "you'll see her switch to..." | **"you'll notice"** (7 hits) — used when pointing at on-screen graphs, timeline overlays, before/after splits |

### 10.3 Long-form-specific vocabulary

Words and phrases Teo uses naturally in long-form channel monologues. Match
these in TTS / when interpreting:

**Channel-meta vocabulary (high frequency):**

- **"video"** (71 hits) / **"channel"** (56 hits) / **"YouTube"** (60 hits) —
  these are intrinsic vocabulary in this register; an IRL clip never uses
  them.
- **"viewers"** / **"audience"** / **"the comments"** — explicit reference
  to the watching audience.
- **"the algorithm"** — referenced casually as a force ("hey, engagement for
  the algorithm").
- **"monetization"** / **"monetized"** / **"demonetized"** — when discussing
  the business of the channel.
- **"posting"** / **"uploading"** / **"the upload"** — cadence vocabulary.
- **"streaming"** / **"Twitch"** — adjacent-platform vocabulary.
- **"my community"** — preferred over "my audience" for the warmer framing.

**Honesty / candor vocabulary (serious-topic register):**

- **"the fact is"** / **"the fact that"** — claim anchor (see §5)
- **"the truth"** / **"the reality was"** — same family
- **"the problem (was/with)"** — problem framing ("Now, the problem with
  using this auto editor is that...")
- **"the point is"** / **"the point being"** — restatement after a digression
- **"to put it"** — qualifier ("to put it out today")
- **"let me just break down what I've been ..."** — admission-setup move
- **"I just have to admit that ..."** — bald-on-record admission
- **"I hope that you can forgive me for ..."** — apology register
- **"perpetuated"** / **"perpetuating"** — used for the act of repeating the
  lie ("I started perpetuating this lie")
- **"set the record straight"** — when correcting a prior framing

**Structural-transition vocabulary:**

- **"at the end of the day, ..."** (8 hits) — section finale (see §5)
- **"with that, ..."** / **"and with that, ..."** — closer, often before
  the outro
- **"before I go, if you are ..."** — outro-CTA setup
- **"I'll see you guys in the next one"** — sign-off (used verbatim in
  multiple videos)
- **"that will be for another video"** — explicit deferral, sets up sequels

**Channel-affectionate audience naming:**

- **"fam"** — in the signature opener ("What's up, fam? It's Teo.")
- **"you guys"** — second-most-common direct address ("I'll see you guys
  in the next one", "I have been lying to you guys for the past couple
  years")
- Never "subscribers", never "Pokemon fans", never "viewers" as a vocative.
  "Viewers" is referential, not address-form.

### 10.4 Long-form sentence-rhythm signature

A typical long-form chapter structure:

1. **Channel-opener** ("What's up, fam? It's Teo. Today, ...") — signature open
2. **Stake-setting / preamble** ("...before we get into anything, I guess we should..." OR "...I've been dealing with, including the fact that...")
3. **Claim** ("**The fact is** that for the past 3 years, approximately, I've been lying to my community.")
4. **Evidence chain** — story, dates, screenshots, before/after — usually 5–20 minutes
5. **Acknowledgement of viewer's likely objection** ("**You might be asking** how I can ...")
6. **Section finale** ("**At the end of the day, ...** [the takeaway].")
7. **Outro CTA + sign-off** ("And with that, I guess I'll see you guys in
   the next one. But now very quickly before I go, if you are ...")

When generating long-form narration in Teo's voice, hit at least 4 of these
blocks per video. The signature **channel-opener** and the
**at-the-end-of-the-day finale** are the two most reliable framing
moves — keep both in any TTS that wants to read as "in the long-form channel
register".

### 10.5 Quick template for a long-form channel sentence

> [Channel-opener: "What's up, fam? It's Teo. Today, ..."] [stake-setting], [honesty-marker: "honestly" / "frankly" / "the fact is"] [the claim, named bluntly]. [Aside that grounds the claim]. [Hook to viewer: "You might be asking ..." or "You'll notice ..."]

Example built from template:

> "What's up, fam? It's Teo. Today, I want to talk about something I should have probably brought up a long time ago. And frankly, the fact is, I haven't been completely upfront about how much time the channel actually takes. You guys see two uploads a week, but the reality is that's about thirty hours of editing per video. And you might be asking, well, why does that matter? At the end of the day, it's the thing that's been keeping me from going full-time on this — and I want to walk you through exactly what changed."

That's the channel-opener, "frankly" + "the fact is" as the honesty stack,
direct audience-naming ("you guys"), "the reality is" as a re-anchor,
"about thirty hours" as an approximate quantifier, "you might be asking"
as the viewer-objection hook, and "at the end of the day" as the finale
pivot. Reads like him in long-form register.

### 10.6 Cross-register usage rule

| If the asset is... | Use register from... |
|---|---|
| 5–60s travel A-roll for a project video (the why-i-love-living-in-japan project) | §1–§7 only |
| 5–60s gameplay TTS for a Pokemon Crystal challenge | §1–§7 + §9 |
| 10+ minute monologue / channel-update / personal-essay long-form | §1–§7 + §10 |
| Short-form vertical 9:16 clip cut FROM a long-form video | §10 register, condensed |

**Do not mix registers in a single voice line.** "What's up, fam, here against Falkner" reads as broken. Pick one register per beat.

---

## 11 · Maintenance

When new A-roll, gameplay, or long-form channel transcripts become available:

1. Skim for new opener patterns, softeners, quantifiers, or vocabulary.
2. Add to §1–§4 (style fundamentals) if patterns recur ≥3 times across IRL content.
3. Add to §9 (Pokemon-gameplay-specific) if patterns recur ≥3 times across gameplay content.
4. Add to §10 (long-form channel monologue) if patterns recur ≥3 times across long-form content.
5. Quote one or two specific examples per new entry.
6. Date-stamp the addition in §12 below.

When mining a new corpus, the canonical workflow is:

```bash
yt-dlp --write-auto-subs --write-subs --sub-lang en --skip-download \
       --convert-subs vtt -o "%(id)s.%(ext)s" <video_url> [...]
# then strip VTT to plain text and run a frequency analyzer over the
# patterns already documented here + candidate-new patterns.
```

Cached corpora live under
`C:\Programming\IRLPC Hyperframes\scratch\irlpc-channel-transcripts\`.

## 12 · Change log

- **2026-05-14** — Initial draft from `IRLPC Why I like Japan` sequence script (12 A-roll clips, ~7 min, ~1,800 words).
- **2026-05-14** — Added §9 (Pokemon gameplay videos — additional patterns) from analysis of the Misty Red and Blue Crystal Gym Leader Challenge transcript (~52 min, ~700 Whisper segments) plus prior Brock challenge context. Covers gameplay-specific vocabulary, narration structure, and a cut-vs-keep guide derived from cut-candidate iteration on the Misty timeline.
- **2026-05-14** — Extended §1–§7 with new patterns mined from all 5 long-form videos on the `@IRLPokemonChallenges` channel (~125 min, ~23,751 words: biggest-youtube-lie, how-i-edit, brutally-honest-working-in-japan, channel-update-2026, permanent-resident). Added new opener rows (channel-signature open, "before we get into anything", "Today, ..."), new softener rows ("sort of", "honestly", "frankly", "I mean", "literally", "obviously", "I guess"), new sentence-rhythm patterns ("at the end of the day" finales, "the fact is/that" claim anchors), and a new "honesty/candor register" subsection in §7. Added an entirely new §10 (Long-form post-edit channel-content register) covering the channel monologue structure: signature open → stake-setting → blunt claim → evidence → viewer-objection acknowledgement → "at the end of the day" finale → outro CTA. Codified the cross-register usage rule (§10.6): IRL travel uses §1–§7, gameplay TTS uses §1–§7+§9, long-form monologue uses §1–§7+§10 — never mix in a single voice line. Renumbered Maintenance → §11 and Change log → §12.
- **2026-05-14** — Extended §9 with patterns mined from 10 videos on the `@RSEPokemonChallenges` channel (~7 hours, ~94,258 words: Eps 17–19 long-form + Mew collab + Eps 23, 24, 27, 32, 37, 38 short/mid) covering the *"How many Pokemon beat Roxanne on Minimum Battles"* Emerald series. Added new battle-action-verb rows ("one-shot" / "two-hit KO" / "three-hitter", "outspeed"), new game-mechanical concepts ("crit / critical hit" — 129 hits, "damage roll" / "good roll", "fish for a freeze", explicit "N% chance" probability narration), new "reaction / outcome interjections" subsection ("massive", "crazy", "nice", "no way", "let's go"), and new "observation- and action-prelude framings" subsection ("let's see" — 82 hits, "let's try", "turns out" — 40 hits, "the question is" — validated at scale). Expanded the formal-noun rules in §9.3 to include the Hoenn Pokemon / move / trainer / item nouns observed in the corpus. Added an entirely new §9.7 ("How many can beat X" minimum-battles series sub-register) with: §9.7.1 comparison table (standard challenge vs. tally series), §9.7.2 compact-attempt sentence frame, §9.7.3 tally / counting vocabulary ("managed to beat Roxanne", "blocked N Pokemon", "eliminate another Pokemon", "the fail column", "member picks", "reduxes"), §9.7.4 probability-narration density, §9.7.5 tally-series-specific cut-vs-keep guidance, and §9.7.6 a worked attempt template. The signature *"Let's go [move] on [target]"* template emerged as the dominant per-attempt strategy-declaration form.
- **2026-05-14** — Validated and revised §9 against a 20-video stratified sample of *finished, published* videos from the main `@RBYPokemonChallenges` channel (~24 hours, ~200K words; 10 most-popular by views 44K–170K + 10 random 1.6K–33K). Cached at `C:\Programming\resolve-mcp\scratch\channel-analysis\transcripts\*.txt`. Major corrections to prior §9 assumptions: (1) **"Smart AI" is NOT Crystal-specific** — it's universal channel vocabulary across Gen 1 and Gen 2 (38 hits across 11/20 videos including pure Gen 1 challenges) — corrected in §9.3. (2) **The "Now," opener is the dominant mid-video transition, NOT the dominant cold-open** — finished videos open with declarative claim or *"today we're going to..."* — caveat added to §9.1 and detailed in §9.8.1. (3) **Audience vocative is "guys", not "folks"**, in current-era videos; "folks" survives only in 2022-era videos — documented in §9.8.5. New high-priority vocabulary added to §9.3: **"minimum battles"** (118 hits / 18 videos — central format constraint, never elide), **"zero DVS / max DVS"** (27 hits / 13 videos), **"Gen 1 miss"**, **"solo run / solo challenge"**, **"the entire game"** (51 hits / 19 videos — never write "the whole game"), **"badge boost(s)"**, **"bad AI / random AI"** as paired antonym to smart AI, plus *"of course"* upgraded to a top-tier softener (226 hits / 19 videos). Added cut-vs-keep refinements to §9.4: rules / constraint explanation blocks always KEEP, external-source corrections (Bulbapedia / Smogon) always KEEP, reset-count and time-stamp meta always KEEP, tier-list / scoring asides always KEEP. Added an entirely new §9.8 (Patterns specific to finished published videos) with §9.8.1 cold-open hook formats (subject-first declarative, *"if you've watched this channel..."*, *"everybody knows that..."*, *"today we're going to find out..."*, series-recap opener), §9.8.2 the *"let's get into it"* pivot from preamble to gameplay (9 hits across 8/20 videos), §9.8.3 outro template (result-summary → audience-thanks → CTA → optional Patreon shoutouts → *"see you in the next [video/one]"* sign-off — 14 hits / 13 videos), §9.8.4 the rules / ruleset block format (*"first things first let's lay down some ground rules"* + *"number one... number two... finally..."* enumeration — 93 hits / 16 videos), §9.8.5 the *"guys"* vs *"folks"* and *"fam"* vocative rule, §9.8.6 the cross-video tier-list / "score" framing, and §9.8.7 a demoted-claims summary documenting what got revised. §9.2 also gained a third aside category (mechanic-explanation asides) that finished videos use to teach the viewer the rule justifying a strategic choice. The most surprising finding: the cold-open hook of the published RBY channel is much more declarative and assertive than the in-progress Misty/Brock data suggested, because the streamer cuts the chatty pre-roll and only keeps the punchiest opening claim.
