# Mario's Super Picross Randomizer

A puzzle randomizer for **Mario's Super Picross** (Super Famicom, 1995). Generates new solutions for all 302 puzzles while preserving the original game engine, clue rendering, and grid sizes.

Every seed produces a unique, complete set of puzzles. The game recomputes clue numbers at runtime from the solution data, so randomized puzzles are fully playable out of the box.

> **Note:** This project was developed with the assistance of AI tools.

## Features

- **302 randomized puzzles** across all grid sizes (5x5, 10x10, 15x15, 20x20, 25x20)
- **Two generation modes**: shuffle existing puzzles or generate entirely new random grids
- **Easy mode**: generates grids with long consecutive runs, producing bigger clue numbers that are more satisfying to solve
- **Difficulty analysis**: built-in scoring system rates every puzzle and flags any that might require guessing
- **Unlock all levels**: ROM patch gives immediate access to all Mario and Wario content
- **Timer freeze**: optional patch locks the timer at 99:59 and only drops if you make a mistake
- **Spoiler log**: full ASCII solution dump for every puzzle


## Quick Start

### Browser (no install required)

Download **`index.html`**, open it in any browser, load your ROM, pick your options, and click Generate. The randomized ROM and spoiler log download directly — nothing is uploaded anywhere.

The browser version produces **byte-identical output** to the Python CLI (verified via SHA-256 across multiple seeds).

### Python CLI

```bash
# Place your Picross.sfc ROM in this directory, then:
python3 rom_randomizer.py --seed 42 --random-grids --easy --unlock-all --no-timer
```

Output:
```
picross_randomized_42.sfc          # Patched ROM 
picross_randomized_42_spoiler.txt  # Full puzzle solutions
```

## CLI Usage

```
python3 rom_randomizer.py --seed <N> [options]
```

| Option | Description |
|--------|-------------|
| `--seed N` | Random seed (required). Seed 0 dumps original puzzles without modification. |
| `--random-grids` | Generate new random solutions instead of shuffling existing ones |
| `--easy` | Easy mode: long consecutive runs instead of scattered cells |
| `--density F` | Fill density for random grids (default: 0.57) |
| `--unlock-all` | Patch ROM to unlock all levels from the start |
| `--no-timer` | Freeze the in-game timer at 99:59 |
| `--analyze` | Print difficulty analysis of generated puzzles |
| `--rom PATH` | Path to input ROM (default: `Picross.sfc` in current directory) |
| `--output-dir PATH` | Output directory (default: current directory) |

## Examples

```bash
# Shuffle existing puzzles (preserves Nintendo's designs, new arrangement)
python3 rom_randomizer.py --seed 99

# Full random with everything unlocked and timer disabled
python3 rom_randomizer.py --seed 777 --random-grids --easy --unlock-all --no-timer

# Hard mode: scattered cells, lower density — for experienced solvers
python3 rom_randomizer.py --seed 1337 --random-grids --density 0.45

# Analyze difficulty without caring about the ROM
python3 rom_randomizer.py --seed 42 --random-grids --easy --analyze

# Extract original puzzle solutions (seed 0 = no modification)
python3 rom_randomizer.py --seed 0
```

## Difficulty Analysis

The `--analyze` flag rates every puzzle on a 0-100 scale based on how much information the clues provide on the first pass:

```
=== DIFFICULTY DISTRIBUTION ===
  Trivial (0-20):   0
  Easy    (21-40):   6
  Medium  (41-60): 208
  Hard    (61-80):  88
  Brutal  (81-100):   0

  No puzzles flagged as likely requiring guessing.
```

The default density of 0.57 was tuned across 1,000 seeds (302,000 puzzles) to virtually eliminate unsolvable puzzles while keeping the difficulty curve interesting:

| Density | Clean Seeds | Avg Difficulty | Character |
|---------|-------------|----------------|-----------|
| 0.45 | 6% | 71.5 | Hard, frequent guessing |
| 0.50 | 76% | 65.9 | Hard, occasional guessing |
| **0.57** | **98.6%** | **57.1** | **Medium-hard, near-zero guessing** |
| 0.65 | 100% | 46.3 | Medium, comfortable |

## How It Works

The randomizer modifies the **solution bitfield** (ROM tag `0x01`) for each puzzle. The game's clue renderer reads the solution at runtime and computes row/column numbers dynamically, so no clue data needs to be modified.

### ROM Patches

| Patch | Description |
|-------|-------------|
| **Unlock** | One-shot fill of the `$07A6` level table + BGM nibble masking to prevent music corruption |
| **Timer** | NOPs the frame counter increment at `$0155` and rewrites the timer init to 99:59 using the game's odometer-wheel encoding |
| **Checksum** | Automatically recalculated after all modifications |

### Grid Generation (Easy Mode)

Easy mode uses a two-pass approach to ensure long runs in **both** directions:

1. Generate horizontal runs with varied density, run count, and gap placement
2. Generate vertical runs (transposed) at reduced density
3. OR the two grids together

This produces clue numbers like `9 3 5` instead of `1 1 2 1 1 1`, making puzzles more satisfying to deduce.

## Known Issue: First Boot with `--unlock-all`

When loading a randomized ROM for the first time (no existing save), the level select cursor will auto-scroll to the bottom of Mario's list. To fix this, press **Left** to switch to Wario mode, then press **Right** to switch back to Mario. All levels will be selectable normally from that point on, including across future play sessions.

## Requirements

- Python 3.8+
- A `Picross.sfc` ROM file (Mario's Super Picross, Japan, 1MB)
- Any SNES emulator (tested with RetroArch + bsnes)

## File Structure

```
index.html          Browser-based randomizer (standalone, no dependencies)
rom_randomizer.py   Python CLI — randomization, ROM patching, analysis
rom_data.py         ROM format parser (pointer table, tagged blocks, bitfields)
ROM_FORMAT.md       Detailed ROM format documentation
```

## Future Updates

- User-supplied puzzles included in the shuffle pool

