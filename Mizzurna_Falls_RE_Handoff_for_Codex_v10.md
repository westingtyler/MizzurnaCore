# Mizzurna Falls (SLPS01783) — Reverse-Engineering Handoff Notes

Purpose: preserve the findings from debugging the Day 3 robbery / code-lock-house softlock in DuckStation via GDB, so a future Codex session can continue without repeating the investigation.

## Environment / workflow

- Game: **Mizzurna Falls**, PS1, serial **SLPS01783**, English patch.
- Emulator: DuckStation.
- GDB server: `127.0.0.1:2345`.
- Windows Python known working:
  - `python`
  - fallback: `C:\Python311\python.exe`
- Main scene/object table:
  - base: `0x800A4418`
  - stride: `0x2A4`
  - slot address: `0x800A4418 + slot * 0x2A4`
- IMPORTANT: **never patch `0x800A3508`**. It is part of the normal main-loop condition and earlier experiments showed it is not the bug.

---

# Bug scenario

Day 3, around 2 PM, after the robbery:

1. Enter the code-lock house.
2. Mel is already invisible/missing from the moment the scene begins.
3. Fight occurs.
4. Bone Head later leaves.
5. Original game softlocks after dialogue / event progression.
6. Game engine is still alive (audio continues, Start/pause can work); it is an event-state stall, not a CPU freeze.

There are actually **two recoverable stalls** in this sequence.

---

# Confirmed structural findings

## Actor / scene-object array

Scene actors are fixed-size records:

```text
actor_base = 0x800A4418
actor_stride = 0x2A4
actor(slot) = actor_base + slot * actor_stride
```

Examples:

```text
slot 13  = 0x800A666C
slot 102 = 0x800B5170
slot 153 = 0x800BD81C
```

## Event-controller actor pointer

Event-controller-like records contain a target actor pointer at approximately:

```text
controller + 0x14
```

This was observed directly in both softlocks.

## Actor state / completion byte

The most important field discovered is:

```text
actor + 0x291
```

This behaves like a **task / action / completion / wait-state byte**.

Do NOT call it a visibility flag. Early in the investigation it was mistaken for one; later experiments disproved that.

The strongest working model is:

```c
while (actor->state_291 != 0) {
    // event controller keeps waiting
}

advance_event();
```

The exact code implementing this polling still needs to be located, but behavior strongly supports this model.

---

# Role lookup finding

A traced event-controller path resolved:

```text
role/id 0x0D -> scene slot 13 -> 0x800A666C
```

At the exact resolved-pointer breakpoint:

```text
v0 = 0x800A666C
v1 = 0x0000000D
s3 = 0x800F6670
```

This proves the controller was resolving ID `0x0D` to slot 13 in this scene.

Caution: do not overstate the semantic identity of role `0x0D` without further proof. Slot 13 participates in the post-Bone event and its state reset causes Matt's missing dialogue/action to occur, but the exact global role-name mapping still deserves independent confirmation.

---

# FIRST SOFTLOCK

Known controller:

```text
controller = 0x800F6670
controller+0x14 -> 0x800A666C
target actor = slot 13
target state = 0x800A666C + 0x291 = 0x800A68FD
```

Observed stuck values at the first stall:

```text
0x800A68FD = 0x04
```

and in another run:

```text
0x800A68FD = 0x06
```

So the exact nonzero value is timing/state-dependent.

## Proven rescue

When the controller still points to slot 13 and the actor's `+0x291` byte is stuck at `0x04` or `0x06`:

```text
write 0x00 to 0x800A68FD
```

This releases the event.

A successful run produced the previously missing Matt action/dialogue:

> "You're not getting away a second time!"

The important correction is that the successful rescue was the later **nonzero -> zero reset**, not merely an earlier experimental `0 -> 2` write.

After the event proceeds, the actor state may become nonzero again. Therefore `0` acts like a completion/idle pulse, not a permanent mode.

---

# SECOND SOFTLOCK

After the first stall is rescued and the cutscene plays through, a second stall occurs near the point where gameplay control should return:

- camera stays on the final cutscene shot
- player movement/control is not returned
- Start/pause still works

At this second stall, the previous controller at `0x800F6670` is cleared.

A different controller becomes active:

```text
controller = 0x800F65F0
controller+0x14 -> 0x800B5170
target actor = slot 102
target state = 0x800B5170 + 0x291 = 0x800B5401
```

Observed stuck value:

```text
0x800B5401 = 0x04
```

## Proven rescue

Write:

```text
0x00 -> 0x800B5401
```

Result:

- camera returns to normal
- player control returns
- controller `0x800F65F0` clears itself
- game continues normally

After the rescue, slot102's `+0x291` can later return to `0x04`, again showing that zero is a completion/idle signal rather than a permanent actor setting.

---

# Practical auto-rescue logic

A working one-click helper uses guarded signatures.

Pseudo-code:

```python
FIRST_CTRL  = 0x800F6670
FIRST_PTR   = 0x800A666C
FIRST_STATE = 0x800A68FD

SECOND_CTRL  = 0x800F65F0
SECOND_PTR   = 0x800B5170
SECOND_STATE = 0x800B5401

if read32(FIRST_CTRL + 0x14) == FIRST_PTR:
    s = read8(FIRST_STATE)
    if s in (0x04, 0x06):
        write8(FIRST_STATE, 0x00)
        resume_game()

elif read32(SECOND_CTRL + 0x14) == SECOND_PTR:
    s = read8(SECOND_STATE)
    if s == 0x04:
        write8(SECOND_STATE, 0x00)
        resume_game()

else:
    # unknown state: do nothing
    pass
```

This worked for both known stalls.

Recommended safety rule for future tools:

```text
verify controller pointer
verify expected actor state
change only one byte
resume
```

If the signature does not match, do not patch anything.

---

# Important corrections / discarded interpretations

These points were investigated and should NOT be treated as current conclusions:

1. `actor+0x291` is **not** simply a visibility flag.
2. Slot 153 was initially suspected to be Mel or the key actor. That was not proven; it later appeared to be a later-spawned actor / police-related object.
3. `0x800A3508` is not the event softlock variable and should not be patched.
4. A generic timer/tick path around `0x800A2828` was not the root cause.
5. Spatial/collision routines such as `0x800182B8` were investigated and were not the event-script blocker.
6. The initial `0 -> 2` experiment on slot13 was useful but misleading as a final explanation. The reliable rescue is **stuck nonzero -> 0** while the appropriate controller is waiting.

---

# Current best model of the bug

The event system appears to synchronize scripted actions with actor-task completion.

Probable structure:

```text
event controller
    |
    +-- +0x14 target actor pointer
              |
              +-- +0x291 action/task/completion state
```

The event controller waits until the actor's `+0x291` reaches zero.

In this broken house sequence, the actor sometimes remains at a nonzero state forever, so the controller never advances.

Manually clearing `actor+0x291` to zero acts as "this actor action completed", allowing the controller to continue and later retire normally.

This same failure pattern occurs at least twice in one cutscene with different controllers and actors.

---

# Why this is useful for reverse engineering other events

For another apparent event/cutscene softlock:

1. Let the game reach the stall naturally.
2. Inspect likely event-controller records around `0x800F6400` and nearby runtime memory.
3. Look for controller records whose `+0x14` points inside the scene actor table.
4. Convert actor pointer to slot:

```text
slot = (actor_ptr - 0x800A4418) / 0x2A4
```

5. Inspect:

```text
actor_ptr + 0x291
```

6. If the controller remains active and `actor+0x291` remains nonzero indefinitely, try a **guarded, reversible test**:
   - verify controller->actor pointer
   - record original byte
   - write zero
   - resume
7. If the event immediately advances and the controller clears, the same wait/completion mechanism is likely involved.

This gives a general method for reverse engineering:
- scripted NPC movement
- animation completion waits
- dialogue/event synchronization
- camera handoff
- control-return logic
- quest/cutscene softlocks

---

# Best next root-cause work

The current fix is a runtime repair, not yet a permanent executable/script patch.

The next useful targets are:

## 1. Find code that READS actor+0x291

At a known softlock, use a read/access watchpoint on:

```text
first stall:  0x800A68FD
second stall: 0x800B5401
```

Goal: identify the exact polling routine / event wait condition.

Likely logic to find:

```c
if (actor->state_291 != 0)
    return_or_wait;
```

Then trace its caller to identify the event opcode / controller state responsible.

## 2. Find code that WRITES actor+0x291

Trace:
- writes of `0x04`
- writes of `0x06`
- normal writes of `0x00`

Goal: find the actor command completion path that should clear this byte but fails in the broken event.

## 3. Determine the earlier Mel invisibility/setup bug

Mel is visibly absent from the instant the player enters the house, before the fight or later softlocks.

This may be:
- the upstream cause of later actor-task completion failures, or
- a separate scene-setup bug.

Do not assume the `+0x291` field is responsible for Mel's visibility.

Useful approach:
- compare actor/role setup on scene entry against another scene where Mel is present
- trace role lookup / actor-spawn code
- identify render/visibility flags independently from `+0x291`

---

# Key code / data landmarks already encountered

Top-level main loop included calls around:

```text
0x80014B30 ...
0x80014B74 lw v0,0xEC(gp)
0x80014B7C beq v0,zero,0x80014B34
```

With:

```text
gp = 0x800A341C
gp+0xEC = 0x800A3508
```

Again: do NOT patch `0x800A3508`.

Useful runtime strings found earlier included:

```text
EM_EVTALK to MARY
EM_TALK to ROLEIN
EM_EVTALK to ROLEIN
EM_TALK to MEL
```

A MEL-related code path was seen around:

```text
0x8002DDB4 ...
0x8002DDFC fallback a1 = 13
...
0x8003FBFC
```

This may eventually help prove the role/character mapping around ID/slot 13.

---

# Known working GDB / RSP details

DuckStation GDB server:
```text
127.0.0.1:2345
```

Software breakpoint:
```text
Z0,address,4
```

Write watchpoint:
```text
Z2,address,length
```

Read/access watchpoint support should be tested with:
```text
Z3,address,length
Z4,address,length
```

DuckStation watchpoints can report a nearby instruction within a write block, so do not always assume the reported PC is the exact byte-writing instruction without decoding the surrounding MIPS.

Observed PC register index in scripts:
```text
37
```

MIPS is little-endian R3000.

---

# Summary for future Codex

The main reusable discovery is:

> Mizzurna Falls appears to use an actor field at structure offset `+0x291` as a task/action completion state. Event-controller structures hold a target actor pointer at approximately `+0x14` and can wait indefinitely while the actor's `+0x291` remains nonzero. In the Day 3 house event, two independent stalls were rescued by safely resetting the waiting actor's `+0x291` byte to zero. The corresponding controllers then advanced/cleared normally.

Known rescues:

```text
FIRST:
  controller 0x800F6670
  target     0x800A666C (slot 13)
  state      0x800A68FD
  observed   04 or 06
  fix        -> 00

SECOND:
  controller 0x800F65F0
  target     0x800B5170 (slot 102)
  state      0x800B5401
  observed   04
  fix        -> 00
```

The next goal is to identify the machine-code routine that polls and clears this field so the workaround can become a true game patch and the same mechanism can be mapped across the rest of the event system.


---

# Additional confirmed case: Father Barton outside-bar event

Scene:
- Outside the bar at approximately 8:30 PM.
- Father Barton gets shoved.
- Matthew intervenes.
- At the very end, as Barton leaves, the event softlocks and the player cannot leave/finish the sequence.

Important visual symptom:
- Barton was invisible for part of this event.
- This resembles the earlier Day 3 house sequence where Mel was invisible before the later event stall.
- This does NOT yet prove that invisibility and the `+0x291` wait-state bug have the same root cause, but it is now a recurring correlation worth investigating.

## Captured softlock state

Generic controller scan found:

```text
controller = 0x800F6670
controller+0x14 -> 0x800A6910
target actor = slot 14
target actor+0x291 = 0x06
```

Since:

```text
actor_base = 0x800A4418
actor_stride = 0x2A4
```

we have:

```text
slot 14 = 0x800A6910
slot14+0x291 = 0x800A6BA1
```

## Proven rescue

At the Barton softlock:

```text
0x800A6BA1: 0x06 -> 0x00
```

Result:
- event resumed successfully
- player was no longer trapped in the sequence

The rescue was guarded by verifying:

```text
controller 0x800F6670 + 0x14 == 0x800A6910
actor state at 0x800A6BA1 == 0x06
```

This is now a THIRD confirmed instance of the same general mechanism:

```text
event controller
    |
    +-- +0x14 target actor
              |
              +-- +0x291 stuck nonzero
                        |
                        +-- reset to 0
                              |
                              +-- event resumes
```

Confirmed examples so far:

```text
Day 3 house, first stall:
  controller 0x800F6670
  slot 13 @ 0x800A666C
  +0x291 @ 0x800A68FD
  stuck 04 or 06
  reset -> 00

Day 3 house, second stall:
  controller 0x800F65F0
  slot 102 @ 0x800B5170
  +0x291 @ 0x800B5401
  stuck 04
  reset -> 00

Father Barton outside-bar event:
  controller 0x800F6670
  slot 14 @ 0x800A6910
  +0x291 @ 0x800A6BA1
  stuck 06
  reset -> 00
```

## New hypothesis strengthened by Barton case

Two broken events now include an NPC becoming invisible before or during the event:

- Mel: invisible from scene entry in the Day 3 house sequence.
- Father Barton: invisible for part of the outside-bar sequence.

Both events later hit an actor-task completion stall recoverable by clearing `actor+0x291`.

This suggests a possible upstream actor-state initialization / transition bug:

```text
bad or incomplete actor setup
        |
        +-- render/visibility state may be wrong
        |
        +-- actor command/task later fails to signal completion
                |
                +-- +0x291 remains nonzero
                        |
                        +-- event controller waits forever
```

This remains a hypothesis. The render/visibility fields have NOT yet been identified, and `+0x291` itself should NOT be treated as a visibility flag.

A high-value future RE target is therefore:
1. compare actor structure fields for visible vs invisible instances of the same character;
2. identify the render/visibility state independently;
3. see whether the same actor setup routine also initializes the task/completion subsystem containing `+0x291`.


---

# Clarification: Barton invisibility begins at scene load

The Barton visibility symptom is stronger than initially recorded.

Observed sequence:
- Player steps outside the bar.
- The cutscene starts immediately.
- Three NPCs are visibly present.
- Father Barton is already invisible from the very beginning of the exterior cutscene.
- Barton is never visibly rendered during the sequence.
- The event later reaches the confirmed slot14 `+0x291 = 0x06` completion stall.

This is important because it argues against Barton merely becoming hidden during a later animation or event transition.

The pattern now closely matches the Day 3 house case:

```text
Day 3 house:
  scene begins
  Mel is already invisible
  later event controller waits on an actor completion state
  actor+0x291 remains nonzero
  resetting it to 0 releases the event

Father Barton exterior:
  scene begins
  Barton is already invisible
  later event controller waits on slot14 completion state
  actor+0x291 = 0x06
  resetting it to 0 releases the event
```

This substantially strengthens the upstream-initialization hypothesis:

```text
scene / role / actor initialization is wrong
        |
        +-- affected NPC never renders from scene entry
        |
        +-- event still has or resolves an actor object for that role
        |
        +-- scripted actor task later enters a nonzero completion state
        |
        +-- normal completion/clear never occurs
        |
        +-- event controller waits forever
```

Important distinction:
- The actor is NOT simply absent from memory.
- In the Barton case, controller `0x800F6670` still points to slot14 at `0x800A6910`.
- Therefore an actor structure exists even though Barton is visually absent.
- This suggests the failure may involve model/render activation, role binding, actor flags, animation/task initialization, or another scene-setup field rather than failure to allocate an actor structure at all.

High-value future RE work:
1. Capture the affected actor structure immediately after scene load, before any dialogue/action.
2. Compare it against:
   - another visible NPC in the same scene;
   - Barton in a scene where he renders correctly, if available;
   - Mel in a scene where Mel renders correctly.
3. Identify fields that differ consistently in invisible-vs-visible instances.
4. Trace writes to those candidate fields during scene initialization.
5. Check whether the same initialization routine also affects the subsystem containing `actor+0x291`.

This is now one of the strongest clues toward the true root cause of the repeated softlocks.


---

# Major clarification: Barton was not truly absent — he was stuck inside the bar

After rescuing the Father Barton outside-bar softlock, the player remained outside
and turned the camera around. Footsteps could be heard. Barton then became visible
inside the bar geometry, continuously walking into the inside face of the door.

This substantially changes the interpretation of the earlier "Barton is invisible"
observation.

Most likely sequence:

```text
exterior cutscene loads
        |
        +-- Barton actor exists and renders
        |
        +-- Barton is positioned on the wrong side of the door / inside the bar
        |
        +-- exterior camera cannot normally see him, so he appears "invisible"
        |
        +-- scripted movement command tells Barton to walk toward/through the doorway
        |
        +-- he collides with or cannot cross the door from this incorrect side
        |
        +-- movement never reaches its destination
        |
        +-- actor+0x291 remains nonzero (observed 0x06)
        |
        +-- event controller waits forever
```

This is a much more concrete root-cause hypothesis than a generic render failure.

Important consequence:
- `actor+0x291` may be tied specifically to an active actor command such as movement,
  rather than being only an abstract "completion flag".
- At the Barton stall, the actor is visibly still executing a locomotion action while
  `+0x291 == 0x06`.
- Clearing `+0x291` to zero tells the event system to treat that action as completed,
  allowing the controller to advance even though the movement did not finish naturally.

This also reframes the earlier Mel case:
- Mel may likewise have been present but spatially misplaced / occluded / trapped rather
  than truly unspawned or non-rendered.
- The house sequence should be re-investigated with camera/position evidence if possible.

High-priority RE target:
1. Identify actor position / destination / movement fields in the 0x2A4-byte actor record.
2. Compare Barton slot14 at:
   - exterior scene load,
   - stuck walking state,
   - a normal visible Barton scene if available.
3. Find which field contains the wrong-side-of-door position.
4. Trace the scene setup / warp code that writes that field.
5. Determine whether the event script supplied the wrong target/position or whether the actor
   failed to transition between interior/exterior coordinate spaces.
6. Trace the movement-completion code that normally clears `actor+0x291`.

The Barton case now suggests the softlock is probably downstream of a spatial/transition bug,
not a primary event-controller bug.


---

# Stronger Barton transition evidence: likely stale interior actor reused outside

Observed sequence in detail:

1. Player is still inside the bar looking for Barton.
2. Barton is visibly walking inside the bar.
3. Player exits the bar.
4. During the loading transition, Barton had just walked past the player inside.
5. Exterior loads.
6. The cutscene starts immediately.
7. The game visibly spawns/places the other three NPCs for the exterior cutscene.
8. Barton is NOT visibly spawned or placed with them.
9. Barton remains unseen during the entire exterior cutscene.
10. After the event, by rotating/clipping the camera back through the building, Barton can be seen still inside the bar, walking into the inside face of the door forever.
11. The event later softlocks with:
    - controller `0x800F6670`
    - target slot14 `0x800A6910`
    - `slot14+0x291 = 0x06`
12. Resetting `slot14+0x291` to zero releases the event.

This strongly suggests the exterior event is operating on an actor object that still has Barton's interior-scene spatial state.

Leading hypothesis:

```text
Barton exists in interior scene
        |
player triggers transition outside
        |
exterior cutscene initializes
        |
other event NPCs are freshly spawned/placed
        |
Barton's role lookup finds/reuses an already-existing actor instance
        |
Barton is NOT re-spawned / re-warped into exterior coordinates
        |
script issues a movement command intended for exterior Barton
        |
the stale interior Barton tries to satisfy it from inside the building
        |
he walks into the door / collision forever
        |
movement completion never fires
        |
actor+0x291 remains nonzero (0x06)
        |
event controller waits forever
```

This is currently a stronger root-cause hypothesis than a generic "wrong position" bug.

Two concrete possibilities remain:

A. **Stale actor reuse / missed transition reset**
   - slot14 persists from the interior scene into the exterior scene;
   - role lookup reuses it;
   - its interior position survives;
   - exterior event assumes it was relocated but it was not.

B. **Bad exterior placement**
   - slot14 is reinitialized for the exterior scene;
   - but the placement/warp writes incorrect coordinates, leaving Barton inside.

The decisive experiment is to capture slot14:
- immediately before exiting the bar;
- immediately after the exterior cutscene places the other NPCs;
- at the final stall.

Compare:
- slot address identity;
- early position-related words;
- resource/model pointers;
- movement/target fields;
- `+0x291`;
- controller target pointer.

If the record is substantially unchanged across the transition, stale actor reuse is strongly supported.
If the record is rebuilt but receives interior-like coordinates, bad placement is more likely.

This also suggests a broader RE angle:
- role lookup may prefer an existing actor object over spawning a new one;
- scene transitions may depend on cleanup/reset logic that is failing for certain NPCs;
- repeated invisible/misplaced NPC bugs may originate in cross-scene actor lifetime management.


---

# Additional Barton lead: cutscene time jump and bar closure may lock in the bad actor state

Observed timing/context:

- Player exited the bar at approximately **8:30 PM Wednesday**.
- The Barton exterior cutscene then played.
- After the cutscene, in-game time had advanced to approximately **1:30 AM**.
- This kind of time jump is normal for Mizzurna Falls cutscenes.
- At 1:30 AM, the bar is closed/locked, so the player cannot simply go back inside.
- Barton was later seen inside the bar geometry, walking into the inside face of the door forever.

This creates a potentially important interaction between:
1. actor persistence across the interior->exterior transition;
2. scripted cutscene time advancement;
3. building/door open-vs-closed state;
4. actor movement completion.

Possible failure chain:

```text
~8:30 PM
Barton exists inside bar
        |
player exits
        |
exterior cutscene begins
        |
other cutscene NPCs are visibly spawned/placed outside
        |
Barton is NOT visibly spawned/placed with them
        |
event still references Barton's existing actor object
        |
Barton remains at interior position / wrong side of doorway
        |
script issues movement intended for exterior Barton
        |
movement cannot complete from stale interior position
        |
cutscene advances clock to ~1:30 AM
        |
bar transitions to closed/locked state
        |
Barton remains physically inside / trapped against doorway
        |
actor+0x291 stays nonzero
        |
event controller waits forever
```

Important caution:
- The bar becoming locked at 1:30 AM is **not yet proven to be the original cause**.
- Barton was already apparently on the wrong side of the transition before the event completed.
- The time jump may instead make the bad state persistent or unrecoverable by changing door/building state while Barton is still trying to satisfy the movement command.

This suggests another useful RE angle:

## Cross-check door/building state against actor task state

On a future controlled reproduction, capture:
- Barton's actor record before leaving the bar;
- the door/open-close state before transition;
- Barton's actor record immediately after the exterior cutscene initializes;
- the door/building state immediately after the time jump;
- `actor+0x291` throughout.

Questions to answer:
1. Does slot14 survive the area transition unchanged?
2. Is Barton's position still in interior coordinates after exterior load?
3. Does the bar door switch from traversable/open to locked before Barton's movement finishes?
4. Is Barton trying to move through a doorway that became non-traversable due to the time jump?
5. Does the actor movement target use exterior coordinates while the actor remains in the interior coordinate space?
6. Is the same cross-scene persistence bug involved in Mel's house-event misplacement?

Current leading interpretation:

> The `+0x291` softlock is likely downstream of a spatial / actor-lifetime / transition bug. The event controller itself may be behaving correctly by waiting for an actor movement/action to complete; the actor never reaches completion because it was not correctly relocated/reinitialized when the scene changed.

This is now a higher-priority root-cause direction than treating `+0x291` itself as the primary bug.


---

# Additional Mel evidence: invisible in jail, interactive, then becomes visible mid-cutscene

A later sequence provides another strong example that an NPC can be logically present
and interactive while visually absent.

Observed sequence after the robbery / arrest:
- Mel is arrested and later should be in a jail cell in the basement.
- On first visit to the cell, Mel is not visibly present.
- Interacting with the cell door still triggers Mel's dialogue.
- Mel responds normally in text/dialogue despite being invisible.
- On a later visit after additional story progress (e.g. checking the motel room),
  interacting with the cell again starts another cutscene.
- Mel initially remains invisible / not visibly present.
- During that cutscene, when he becomes hostile/aggressive, he suddenly pops into visibility.
- Once visible, he appears to be acting aggressively against the inside of the cell door.

This is highly relevant because it proves:

```text
invisible != absent actor
```

The game can still:
- resolve Mel as the correct role/character;
- trigger his dialogue;
- execute scripted behavior involving him;

while his model is not being rendered.

A later scripted action can apparently transition him into a visible state.

This suggests several candidate failure modes:

1. **Render/model activation state is stale or unset**
   - actor exists;
   - role binding works;
   - dialogue/event logic works;
   - model/render state is disabled until a later action reinitializes it.

2. **Actor is spatially misplaced / occluded**
   - actor exists but is on the wrong side of collision/door geometry;
   - later action changes position or animation enough to make him visible.

3. **Task/action initialization partially repairs the actor**
   - a new scripted command may write fields that were missing/stale;
   - the aggressive action may incidentally restore render/animation state.

4. **Door-side / room-boundary state is involved**
   - once visible, Mel is again seen acting against the inside of a door;
   - this strongly resembles Barton being stuck walking into the inside of the bar door.

The repeated door-boundary pattern is now notable:

```text
Barton:
  persists / remains inside bar
  walks into inside face of door forever
  movement completion stalls

Mel:
  invisible in jail
  still responds through cell-door interaction
  later pops visible during hostile action
  then acts against inside of cell door
```

This makes "door / room-boundary actor transition state" a high-priority RE theme.

Current stronger working model:

```text
actor object exists
        |
role/event lookup still works
        |
scene / room / door transition leaves actor in stale spatial/render/task state
        |
actor may be invisible or on wrong side of boundary
        |
later scripted movement/action targets that actor
        |
action may:
    - fail forever, causing +0x291 softlock
    - or partially reinitialize actor and make it visible
```

This also weakens any hypothesis that the core bug is simply "actor failed to spawn."
The actor can clearly exist and participate in dialogue while invisible.

High-value future comparisons:
- Mel jail actor structure while invisible vs immediately after he pops visible.
- Barton interior actor before exit vs exterior event after transition.
- Any same-character visible scene for baseline.
- Watch writes around the exact frame where Mel becomes visible.
- Identify whether the visibility transition correlates with:
  - model/resource pointer changes;
  - position fields;
  - animation/task fields;
  - actor flags;
  - `+0x291`;
  - room/door/collision state.

If a small group of fields changes exactly when Mel appears, those fields may expose the
actual render/spatial activation mechanism that is upstream of the later completion stalls.


---

# Consolidated Future Capture Checklist

This section consolidates the highest-value future captures/experiments mentioned throughout this handoff.

## A. Find the event wait routine for `actor+0x291`

At a known softlock, set a read/access watchpoint on the waiting actor's `+0x291` byte.

Known examples:

```text
Day 3 house first stall:  0x800A68FD
Day 3 house second stall: 0x800B5401
Barton outside-bar stall: 0x800A6BA1
```

Goal:
- identify the exact code polling this field;
- confirm whether the logic is effectively:

```c
if (actor->state_291 != 0)
    keep_waiting();
```

Then trace the caller to identify the event opcode/controller state that requested the wait.

## B. Find who WRITES `actor+0x291`

Trace writes of:
- `0x04`
- `0x06`
- normal completion write `0x00`

Goal:
- identify the actor command/task state machine;
- identify the normal completion path;
- determine why the broken movement/action fails to reach the `0x00` completion state.

## C. Barton interior -> exterior transition capture

Capture slot14 (`0x800A6910`) at three stages:

1. **Inside the bar immediately before exit**
2. **Immediately after the exterior cutscene initializes / other NPCs are placed**
3. **At the final Barton softlock**

Compare:
- whether slot14 remains the same actor record;
- early position-related words;
- model/resource pointers;
- animation/task fields;
- movement target fields;
- `+0x291`;
- controller `+0x14`.

Purpose:
- distinguish **stale interior actor reuse** from **bad exterior placement**.

## D. Barton wrong-side / door-state capture

While Barton is visibly inside the bar walking into the inside face of the door, capture:

- full slot14 actor record;
- likely movement/position fields;
- controller state;
- nearby actors for comparison;
- door/building state if identifiable.

Goal:
- determine actor current position vs target position;
- determine whether collision/door state prevents reaching the target.

## E. Time-jump / bar-lock interaction

On a controlled reproduction around the ~8:30 PM -> ~1:30 AM cutscene jump, capture:

- Barton actor before leaving the bar;
- bar door/open-close state before transition;
- Barton immediately after exterior cutscene initialization;
- door/building state immediately after time jump;
- `actor+0x291` throughout.

Questions:
- Does the bar become non-traversable before Barton's movement finishes?
- Does the time jump merely lock in an already-bad state, or actively cause it?

## F. Mel jail invisible -> visible transition

Capture Mel's actor record:

1. while invisible but still responding through the cell door;
2. immediately before the hostile cutscene;
3. immediately after he pops into visibility.

Watch writes around the exact frame he becomes visible.

Compare changes in:
- model/resource pointers;
- position fields;
- animation/task fields;
- actor flags;
- `+0x291`;
- room/door/collision-related state.

Purpose:
- identify the field(s) controlling the broken render/spatial activation state.

## G. Mel house scene-entry capture

At the Day 3 house event, capture the actor/role state as early as possible when the scene loads and Mel is already unseen.

Compare against:
- Mel in a known-good visible scene;
- Mel in jail once visible;
- visible NPCs in the same house scene.

Goal:
- determine whether Mel is:
  - spatially misplaced;
  - occluded/on the wrong side of geometry;
  - present with render/model activation missing;
  - using a stale actor record from another scene.

## H. Same-character good-scene baselines

For both Mel and Barton, obtain at least one actor-record capture from a scene where each character renders and behaves normally.

Use these as baselines for:
- position/layout fields;
- resource pointers;
- actor flags;
- task state;
- room/scene ownership;
- model/animation activation.

## I. Role lookup / actor lifetime tracing

Trace:
- role lookup when an event requests Mel/Barton;
- whether lookup prefers an existing actor object;
- whether scene transitions destroy/recreate or reuse that object;
- writes to actor records during scene/room transitions.

Goal:
- test the stale-role / stale-actor reuse hypothesis directly.

## J. Door / room-boundary subsystem

Because both Barton and Mel have now been observed interacting incorrectly with the **inside face of a door**, identify:

- door collision state;
- room ownership / area IDs;
- interior vs exterior coordinate-space state;
- transition/warp routines;
- any actor field that changes when crossing a room boundary normally.

Compare a normal NPC doorway traversal against the broken Barton/Mel cases.

## K. General procedure for any new softlock

For any future event stall:

1. Scan controller runtime for live `controller+0x14 -> actor` links.
2. Convert actor pointer to slot:
   ```text
   slot = (actor_ptr - 0x800A4418) / 0x2A4
   ```
3. Inspect `actor+0x291`.
4. If nonzero and the controller remains active indefinitely, capture before modifying.
5. Perform a guarded `actor+0x291 -> 0` test.
6. If the event advances, record:
   - controller address;
   - actor slot/address;
   - stuck byte value;
   - scene context;
   - whether actor was misplaced/invisible/stuck in movement.
7. Preserve the case as another instance of the same event-wait mechanism.


---

# Wednesday chronology of observed failures

All of the major observations described in this handoff occurred on the same in-game day: **Wednesday**.

Approximate user-observed timeline:

```text
~1:30 PM Wednesday
  Robbery / house event sequence.
  This is the sequence containing the first major softlocks:
  - post-Bone stall involving slot13 / controller 0x800F6670
  - later control-return stall involving slot102 / controller 0x800F65F0

~5:00 PM Wednesday
  Mel-related jail/cell sequence.
  Mel can be logically present and respond in dialogue while invisible.
  On a later interaction, he becomes visible mid-cutscene during a hostile/aggressive action
  near the inside of the cell door.

~8:30 PM Wednesday
  Father Barton outside-bar event.
  Player exits the bar and the exterior cutscene starts.
  Barton is not visibly placed with the other exterior NPCs.
  He is later found still inside the bar, walking into the inside face of the door.
  Event softlocks with:
    controller 0x800F6670
    slot14 @ 0x800A6910
    slot14+0x291 = 0x06
  Resetting that byte to zero releases the event.

After the Barton cutscene:
  in-game time advances to approximately 1:30 AM
  and the bar is closed/locked.
```

These times are approximate observations from play, not yet verified against event-script time constants.

Why this chronology matters:

- the failures are clustered on one story day;
- the affected NPC/event state may accumulate or persist across several Wednesday scenes;
- stale actor/role state may survive between events;
- scene transitions and time-of-day changes may expose the same underlying actor-lifetime bug repeatedly;
- Wednesday-specific event scheduling or cleanup logic may be involved.

High-value future question:

> Is there a Wednesday-only actor/role state or cleanup path that fails after the robbery sequence and then contaminates later Mel/Barton events?

This suggests checking:
- actor/role tables before the ~1:30 PM robbery event;
- immediately after it;
- around the ~5 PM Mel jail event;
- around the ~8:30 PM Barton event;
- after large cutscene-driven time jumps.

If one stale actor/role entry persists across all three time windows, that could unify the currently separate-looking symptoms.

---

# Confirmed softlock fixes — named bug entries

This section records the three confirmed softlocks using the project-facing names:

- `MelRobbersShack_OnYourOwn`
- `MelRobbersShack_EndOfSceneReturn`
- `FatherBarton_OutsideBarAttack`

These are **confirmed runtime rescues**. They are not yet the final permanent executable/script fixes.

## Shared mechanism

All three use the same observed event-wait pattern:

```text
event controller
    |
    +-- controller+0x14 -> target actor
                              |
                              +-- actor+0x291 remains nonzero
                                      |
                                      +-- controller waits forever
```

Actor table:

```text
base   = 0x800A4418
stride = 0x2A4
actor(slot) = base + slot * stride
```

`actor+0x291` behaves like an actor task/action/completion state.

Important:
- it is **not** a visibility flag;
- `0x00` behaves like a completion/idle signal;
- clearing it allows the waiting event controller to advance.

---

## MelRobbersShack_OnYourOwn

### Symptom

Wednesday robbery / robbers' shack sequence, approximately early afternoon.

After Bone Head leaves, the sequence stalls instead of advancing correctly. The game engine remains alive.

### Confirmed runtime signature

```text
controller        = 0x800F6670
controller+0x14   = 0x800A666C
target actor      = slot 13
actor+0x291       = 0x800A68FD
```

Observed stuck values:

```text
0x04
0x06
```

### Confirmed rescue

Guarded fix:

```text
if read32(0x800F6670 + 0x14) == 0x800A666C:
    if read8(0x800A68FD) == 0x04 or 0x06:
        write8(0x800A68FD, 0x00)
```

Result:

- the event resumes;
- Matt performs the previously missing action/dialogue;
- `"You're not getting away a second time!"` occurs;
- the cutscene proceeds.

### Important correction

An earlier `0x02` experiment appeared useful, but later testing showed the reliable rescue is:

```text
stuck nonzero state -> 0x00
```

The actual working values observed were:

```text
0x04 -> 0x00
0x06 -> 0x00
```

---

## MelRobbersShack_EndOfSceneReturn

### Symptom

Second stall in the same robbery / shack sequence.

After the restored cutscene finishes:

- the final cutscene camera remains active;
- player control is not returned;
- Start/pause still works;
- the engine is still alive.

### Confirmed runtime signature

```text
controller        = 0x800F65F0
controller+0x14   = 0x800B5170
target actor      = slot 102
actor+0x291       = 0x800B5401
stuck value       = 0x04
```

### Confirmed rescue

```text
if read32(0x800F65F0 + 0x14) == 0x800B5170:
    if read8(0x800B5401) == 0x04:
        write8(0x800B5401, 0x00)
```

Result:

- camera returns to normal;
- player control returns;
- controller `0x800F65F0` clears itself;
- gameplay continues normally.

The actor byte can later become nonzero again, confirming that `0x00` is a completion/idle signal rather than a permanent mode.

---

## FatherBarton_OutsideBarAttack

### Symptom

Wednesday, approximately 8:30 PM, outside the bar.

Father Barton gets shoved, Matthew intervenes, and the event later stalls as Barton is supposed to leave.

### Confirmed runtime signature

```text
controller        = 0x800F6670
controller+0x14   = 0x800A6910
target actor      = slot 14
actor+0x291       = 0x800A6BA1
stuck value       = 0x06
```

### Confirmed rescue

```text
if read32(0x800F6670 + 0x14) == 0x800A6910:
    if read8(0x800A6BA1) == 0x06:
        write8(0x800A6BA1, 0x00)
```

Result:

- event resumes;
- player is released from the sequence.

### Strong spatial/root-cause evidence

Barton was visible **inside the bar immediately before the player exited**.

Then:

1. the player exited;
2. the exterior cutscene started;
3. the other exterior NPCs were visibly placed;
4. Barton was not visibly placed with them;
5. after the event, clipping the camera back through the building showed Barton still inside the bar;
6. Barton was walking continuously into the inside face of the door.

This strongly suggests:

```text
Barton retains stale/wrong interior position
        ->
exterior scripted movement starts
        ->
movement destination cannot be reached
        ->
movement never completes
        ->
actor+0x291 remains 0x06
        ->
event controller waits forever
```

The cutscene advances time from roughly 8:30 PM to roughly 1:30 AM, after which the bar is closed/locked.

That time/door-state change may make the bad state persistent, but it is **not yet proven to be the original cause**.

---

# Compact confirmed rescue table

```text
MelRobbersShack_OnYourOwn
  controller  = 0x800F6670
  actor       = 0x800A666C  (slot 13)
  state byte  = 0x800A68FD
  stuck       = 0x04 or 0x06
  rescue      = write 0x00

MelRobbersShack_EndOfSceneReturn
  controller  = 0x800F65F0
  actor       = 0x800B5170  (slot 102)
  state byte  = 0x800B5401
  stuck       = 0x04
  rescue      = write 0x00

FatherBarton_OutsideBarAttack
  controller  = 0x800F6670
  actor       = 0x800A6910  (slot 14)
  state byte  = 0x800A6BA1
  stuck       = 0x06
  rescue      = write 0x00
```

Always verify the controller's `+0x14` actor pointer before changing the actor byte.

---

# Permanent-patch direction for these three bugs

The current RAM writes prove where each event is blocked.

The preferred permanent fix is to correct the **upstream actor/task failure**, not simply force completion globally.

Current best model:

```text
actor starts in stale/wrong spatial or task state
        ->
scripted movement/action cannot complete
        ->
actor+0x291 never reaches 0
        ->
event controller waits forever
```

High-value next work:

1. Find the code that **reads** `actor+0x291`.
2. Find the code that writes `0x04`, `0x06`, and normal `0x00`.
3. Identify the movement/task completion routine.
4. For Barton, prove whether slot14 survives the interior->exterior transition unchanged or is reinitialized with bad coordinates.
5. For Mel, compare invisible and visible actor states to determine whether the same stale spatial/task mechanism is involved.
6. Convert the runtime rescue into a build-specific permanent patch for Japanese / Cirosan-Nikita / Owl as needed.
