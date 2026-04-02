#!/usr/bin/env python3
"""
Mario's Super Picross — ROM Randomizer
========================================

Reads all 302 puzzles from the ROM, randomizes them, and writes
a new ROM file with a spoiler log.

Modes:
  seed 0:  Dump existing puzzles (no modification) — PoC/extraction
  seed N:  Randomize puzzles using seed N

Randomization strategy:
  - Shuffles puzzles within each grid size group
  - Optionally generates fully random solutions (--random-grids)
  - Preserves grid size per slot (5x5 stays 5x5, etc.)

Output:
  - New ROM file: picross_randomized_<seed>.sfc
  - Spoiler log:  picross_randomized_<seed>_spoiler.txt

Usage:
  python3 rom_randomizer.py --seed 0                    # Dump existing
  python3 rom_randomizer.py --seed 42                   # Shuffle puzzles
  python3 rom_randomizer.py --seed 42 --random-grids    # Fully random solutions
  python3 rom_randomizer.py --seed 42 --unlock-all      # Unlock all levels
"""

import argparse
import math
import os
import random

from rom_data import (
    read_all_puzzles, write_puzzle_solution, fix_rom_checksum,
    encode_solution_bitfield, Puzzle,
)

DEFAULT_ROM = os.path.join(os.path.dirname(__file__), "Picross.sfc")
OUTPUT_DIR = os.path.dirname(__file__) or "."


def generate_random_grid(cols, rows, density=0.5, rng=None, easy=False):
    """Generate a random puzzle grid.

    Normal (hard) mode: each cell independently random at given density.
    Produces scattered, fragmented clue numbers — harder to solve
    because many small numbers create more ambiguity.

    Easy mode (--easy): generates long consecutive runs per row with
    minimal gaps. Big clue numbers (9+) are easier to place and solve.
    """
    if rng is None:
        rng = random

    if easy:
        grid = _generate_easy_grid(cols, rows, density, rng)
    else:
        grid = []
        for r in range(rows):
            row = []
            for c in range(cols):
                row.append(rng.random() < density)
            grid.append(row)

    if not easy:
        # Ensure at least one cell per row and column for valid clues
        # (Easy mode intentionally allows empty rows/columns)
        for r in range(rows):
            if not any(grid[r]):
                grid[r][rng.randint(0, cols - 1)] = True
        for c in range(cols):
            if not any(grid[r][c] for r in range(rows)):
                grid[rng.randint(0, rows - 1)][c] = True

    return grid


def _generate_easy_grid(cols, rows, density, rng):
    """Generate a grid with long consecutive runs in BOTH directions.

    Two-pass approach:
    1. Generate horizontal runs (row-based)
    2. Generate vertical runs (column-based)
    3. OR the two grids together

    This ensures both row and column clue numbers include large values.
    """
    # Pass 1: horizontal runs
    h_grid = _generate_run_grid(cols, rows, density, rng)

    # Pass 2: vertical runs (transpose, generate, transpose back)
    v_grid_t = _generate_run_grid(rows, cols, density * 0.3, rng)
    v_grid = [[v_grid_t[c][r] for c in range(cols)] for r in range(rows)]

    # OR the two grids — cells filled in either pass stay filled
    grid = []
    for r in range(rows):
        row = [h_grid[r][c] or v_grid[r][c] for c in range(cols)]
        grid.append(row)

    return grid


def _generate_run_grid(cols, rows, density, rng):
    """Generate a grid with long runs per row."""
    grid = []
    for r in range(rows):
        row = [False] * cols
        roll = rng.random()

        if roll < 0.06:
            pass  # Empty row
        elif roll < 0.12:
            row = [True] * cols  # Full row
        else:
            row_density = density + rng.uniform(-0.20, 0.20)
            row_density = max(0.10, min(0.85, row_density))
            filled_target = max(1, int(cols * row_density))

            num_runs = rng.choices([1, 2, 3], weights=[3, 5, 2])[0]
            if cols < 10:
                num_runs = min(num_runs, 2)

            runs = []
            remaining = filled_target
            for i in range(num_runs):
                if remaining <= 0:
                    break
                if i == num_runs - 1:
                    run_len = remaining
                else:
                    min_len = max(1, remaining // (num_runs - i) // 2)
                    max_len = max(min_len, remaining - (num_runs - i - 1))
                    run_len = rng.randint(min_len, max_len)
                runs.append(max(1, run_len))
                remaining -= run_len

            rng.shuffle(runs)

            total_run = sum(runs)
            total_gaps = max(0, cols - total_run)
            if runs:
                gap_slots = len(runs) + 1
                gaps = [0] * gap_slots
                for _ in range(total_gaps):
                    gaps[rng.randint(0, gap_slots - 1)] += 1

                pos = gaps[0]
                for idx, run_len in enumerate(runs):
                    for c in range(pos, min(pos + run_len, cols)):
                        row[c] = True
                    pos += run_len + gaps[idx + 1]

        grid.append(row)
    return grid


def shuffle_puzzles(puzzles, rng):
    """Shuffle puzzles within each grid size group.

    Puzzles of the same size swap solutions, preserving the
    slot's grid dimensions and ROM layout.
    """
    # Group by size
    by_size = {}
    for p in puzzles:
        key = (p.cols, p.rows)
        if key not in by_size:
            by_size[key] = []
        by_size[key].append(p)

    # Shuffle grids within each group
    new_grids = {}
    for size, group in by_size.items():
        grids = [p.grid for p in group]
        rng.shuffle(grids)
        for p, new_grid in zip(group, grids):
            new_grids[p.index] = new_grid

    return new_grids


def randomize_all_grids(puzzles, rng, density=0.5, easy=False):
    """Generate completely random solutions for all puzzles."""
    new_grids = {}
    for p in puzzles:
        new_grids[p.index] = generate_random_grid(p.cols, p.rows, density, rng, easy=easy)
    return new_grids


# =============================================================================
# DIFFICULTY ANALYSIS
# =============================================================================

def _get_clues(line):
    """Extract picross clue numbers from a row/column of booleans."""
    clues, run = [], 0
    for c in line:
        if c:
            run += 1
        elif run:
            clues.append(run)
            run = 0
    if run:
        clues.append(run)
    return clues or [0]


def _line_overlap(clues, length):
    """Count cells determinable from one line's clues (overlap method).

    For each clue number, the overlap is how many cells are filled
    regardless of where the run is placed. A clue of [0] (empty line)
    determines all cells as empty.
    """
    if clues == [0]:
        return length
    min_space = sum(clues) + len(clues) - 1
    slack = length - min_space
    if slack < 0:
        return 0
    if slack == 0:
        return length
    return sum(max(0, c - slack) for c in clues)


def analyze_grid(grid, cols, rows):
    """Compute difficulty metrics for a single puzzle grid.

    Returns a dict with:
      difficulty:  0 (trivial) to 100 (likely impossible)
      info_ratio:  fraction of cells determinable on first pass
      avg_clue:    mean clue number across all lines
      max_clue:    largest single clue number
      useless:     lines where clues give zero overlap info
      total_lines: rows + cols
      density:     fraction of cells filled
    """
    row_clues = [_get_clues(grid[r]) for r in range(rows)]
    col_clues = [_get_clues([grid[r][c] for r in range(rows)])
                 for c in range(cols)]
    all_clues = row_clues + col_clues
    total_cells = rows * cols
    total_lines = rows + cols

    row_det = sum(_line_overlap(rc, cols) for rc in row_clues)
    col_det = sum(_line_overlap(cc, rows) for cc in col_clues)
    info_ratio = (row_det + col_det) / (total_cells * 2)

    all_nums = [c for cl in all_clues for c in cl if c > 0]
    avg_clue = sum(all_nums) / len(all_nums) if all_nums else 0
    max_clue = max((c for cl in all_clues for c in cl), default=0)

    useless = sum(1 for i, cl in enumerate(all_clues)
                  if all(c == 1 for c in cl) and
                  _line_overlap(cl, cols if i < rows else rows) == 0)

    density = sum(c for row in grid for c in row) / total_cells

    difficulty = int(
        100 * (1 - info_ratio)
        * (0.3 + 0.7 * (1 - avg_clue / max(cols, rows)))
    )
    difficulty = max(0, min(100, difficulty))

    return {
        'difficulty': difficulty,
        'info_ratio': info_ratio,
        'avg_clue': avg_clue,
        'max_clue': max_clue,
        'useless': useless,
        'total_lines': total_lines,
        'density': density,
    }


def print_analysis(puzzles, grids):
    """Print difficulty analysis for a set of puzzles."""
    results = []
    for p in puzzles:
        grid = grids[p.index] if grids else p.grid
        a = analyze_grid(grid, p.cols, p.rows)
        results.append((p, a))

    # Distribution
    buckets = [
        ('Trivial (0-20)', 0, 20),
        ('Easy    (21-40)', 21, 40),
        ('Medium  (41-60)', 41, 60),
        ('Hard    (61-80)', 61, 80),
        ('Brutal  (81-100)', 81, 100),
    ]
    print("\n=== DIFFICULTY DISTRIBUTION ===")
    for label, lo, hi in buckets:
        group = [(p, a) for p, a in results if lo <= a['difficulty'] <= hi]
        sizes = {}
        for p, _ in group:
            sizes[p.size_name] = sizes.get(p.size_name, 0) + 1
        size_str = (', '.join(f'{v}x {k}' for k, v in sorted(sizes.items()))
                    if sizes else 'none')
        print(f"  {label}: {len(group):3d}  ({size_str})")

    # Top 10 hardest
    results.sort(key=lambda x: -x[1]['difficulty'])
    print("\n=== TOP 10 HARDEST ===")
    for p, a in results[:10]:
        name = f"{p.level + 1}-{chr(65 + p.position)}"
        print(f"  {name:8s} [{p.size_name}]  diff={a['difficulty']:3d}  "
              f"info={a['info_ratio']:.1%}  avg_clue={a['avg_clue']:.1f}  "
              f"useless={a['useless']}/{a['total_lines']}  "
              f"density={a['density']:.0%}")

    # Flag suspect puzzles
    suspect = [(p, a) for p, a in results if a['info_ratio'] < 0.05]
    if suspect:
        print(f"\n=== LIKELY REQUIRES GUESSING ({len(suspect)}) ===")
        for p, a in suspect[:15]:
            name = f"{p.level + 1}-{chr(65 + p.position)}"
            print(f"  {name:8s} [{p.size_name}]  diff={a['difficulty']:3d}  "
                  f"info={a['info_ratio']:.1%}  avg_clue={a['avg_clue']:.1f}")
    else:
        print("\n  No puzzles flagged as likely requiring guessing.")

    # 5 easiest
    results.sort(key=lambda x: x[1]['difficulty'])
    print("\n=== 5 EASIEST ===")
    for p, a in results[:5]:
        name = f"{p.level + 1}-{chr(65 + p.position)}"
        print(f"  {name:8s} [{p.size_name}]  diff={a['difficulty']:3d}  "
              f"info={a['info_ratio']:.1%}  avg_clue={a['avg_clue']:.1f}")


def write_spoiler_log(path, puzzles, new_grids=None):
    """Write ASCII spoiler file with all puzzle solutions."""
    with open(path, "w") as f:
        f.write("Mario's Super Picross — Puzzle Solutions\n")
        f.write("=" * 50 + "\n\n")

        if new_grids:
            f.write("** RANDOMIZED **\n\n")

        current_mode = None
        current_level = None

        for p in puzzles:
            # Section headers
            if p.mode != current_mode:
                current_mode = p.mode
                current_level = None
                f.write(f"\n{'='*50}\n")
                f.write(f"  {p.mode.upper()} MODE\n")
                f.write(f"{'='*50}\n\n")

            if p.level != current_level:
                current_level = p.level
                f.write(f"--- Level {p.level + 1} ---\n\n")

            grid = new_grids[p.index] if new_grids else p.grid
            cell_count = sum(cell for row in grid for cell in row)

            f.write(f"Puzzle {p.level + 1}-{chr(65 + p.position)} "
                    f"[{p.size_name}, {cell_count} cells]\n")
            for row in grid:
                f.write("  " + " ".join("#" if c else "." for c in row) + "\n")
            f.write("\n")

    return path


def apply_unlock_rom_patch(rom_data):
    """Patch ROM to unlock all Mario and Wario levels (ROM-only).

    The $07A6 table encodes per-mode, per-level-group data: level
    counts, completion state, and BGM indices all packed into nibbles
    of shared bytes. Some entries are legitimately zero (unused level
    groups), so filling with a constant value breaks the menu cursor.

    Instead, this patch embeds the exact table values from a fully-
    completed save file and writes them on first access via a hook
    at $3492. The guard skips if the table is already populated
    (e.g. from an existing save).

    Patches:
      $3492: JMP $F220  (one-shot table init hook)
      $F220: Guard + byte-exact table init from save data
    """
    # Table values for full unlock of both modes.
    # $BB per byte: high nibble $B = 11 level groups (10 worlds +
    # bonus), low nibble $B = completion state passes all CMP checks.
    # Verified: the game uses count=11 ($0E4A=$0B) when fully unlocked.
    # BGM nibble $B is invalid (>3) but handled by the clamp patch below.
    TABLE_DATA = bytes([0xBB, 0xBB] * 12)

    # Hook at $3492: replace LDA $07A6,X with JMP $F220
    rom_data[0x3492] = 0x4C  # JMP
    rom_data[0x3493] = 0x20  # $F220 low
    rom_data[0x3494] = 0xF2  # $F220 high

    # Build patch routine at $F220
    patch = bytearray()
    # Guard: skip if table already populated
    patch.extend([0xAD, 0xA6, 0x07])  # LDA $07A6
    patch.extend([0xD0])              # BNE → skip
    fill_start = len(patch)
    patch.extend([0x00])              # placeholder offset

    # Write each 16-bit word from the save data
    for i in range(0, len(TABLE_DATA), 2):
        lo, hi = TABLE_DATA[i], TABLE_DATA[i + 1]
        word = lo | (hi << 8)
        addr = 0x07A6 + i
        if word == 0x0000:
            # STZ is shorter and already zero on fresh WRAM, but
            # be explicit for clarity
            patch.extend([0x9C, addr & 0xFF, (addr >> 8) & 0xFF])
        else:
            patch.extend([0xA9, lo, hi])  # LDA #imm16
            patch.extend([0x8D, addr & 0xFF, (addr >> 8) & 0xFF])  # STA abs

    # Fix up branch offset
    skip_target = len(patch)
    patch[fill_start] = skip_target - fill_start - 1

    # Original instruction + return
    patch.extend([0xBD, 0xA6, 0x07])  # LDA $07A6,X
    patch.extend([0x4C, 0x95, 0x34])  # JMP $3495

    rom_data[0xF220:0xF220 + len(patch)] = patch

    # BGM fix: mask both reads from $07AA to 2 bits (valid range 0-3).
    # The $BB fill sets BGM nibbles to $B (invalid). Two code paths
    # read the nibble — both need fixing:
    #   $4291: AND #$000F → AND #$0003  (BGM display/menu)
    #   $42A3: AND #$000F → AND #$0003  (BGM playback)
    # $B AND $03 = $03 (BGM 4), a valid default. Once the user picks
    # a BGM (0-3), it persists. "Off" (value 4) wraps to 0 on re-read
    # but this is an acceptable trade-off for ROM-only unlock.
    rom_data[0x4292] = 0x03  # AND #$0003 (was #$000F)
    rom_data[0x42A4] = 0x03  # AND #$0003 (was #$000F)


def apply_no_timer_patch(rom_data):
    """Patch ROM to freeze the in-game timer at 99:59.

    Two patches:
    1. NOP the INC $0FDE at $0155 so the frame counter never ticks.
    2. Rewrite the timer init routine at $8675 to always set 99:59
       using the odometer-wheel encoding (each digit = $02 units):
         $0FE2=$12 (sec ones=9), $0FE3=$0A (sec tens=5),
         $0FE4=$12 (min ones=9), $0FE5=$12 (min tens=9).
    """
    # Patch 1: freeze frame counter
    # $0155: EE DE 0F (INC $0FDE) → EA EA EA (NOP NOP NOP)
    rom_data[0x0155] = 0xEA
    rom_data[0x0156] = 0xEA
    rom_data[0x0157] = 0xEA

    # Patch 2: rewrite timer init at $8675-$868D (25 bytes available)
    # Replaces mode-dependent init (Mario=30:00, Wario=0:00) with
    # unconditional 99:59 for both modes.
    patch = bytearray([
        0x9C, 0xE6, 0x0F,        # STZ $0FE6
        0x9C, 0xDE, 0x0F,        # STZ $0FDE       ; frame counter = 0
        0xA9, 0x12, 0x0A,        # LDA #$0A12
        0x8D, 0xE2, 0x0F,        # STA $0FE2       ; sec ones=9, sec tens=5
        0xA9, 0x12, 0x12,        # LDA #$1212
        0x8D, 0xE4, 0x0F,        # STA $0FE4       ; min ones=9, min tens=9
        0x6B,                    # RTL
    ])
    # Pad remaining bytes with NOPs
    patch.extend([0xEA] * (25 - len(patch)))
    rom_data[0x8675:0x8675 + len(patch)] = patch


def main():
    parser = argparse.ArgumentParser(
        description="Mario's Super Picross ROM Randomizer")
    parser.add_argument("--rom", default=DEFAULT_ROM,
                        help=f"Input ROM path (default: {DEFAULT_ROM})")
    parser.add_argument("--seed", type=int, required=True,
                        help="Random seed (0 = dump existing, no changes)")
    parser.add_argument("--random-grids", action="store_true",
                        help="Generate random solutions (hard — scattered clues)")
    parser.add_argument("--easy", action="store_true",
                        help="Easy mode: long consecutive runs instead of scatter")
    parser.add_argument("--density", type=float, default=0.57,
                        help="Fill density for --random-grids (default: 0.57)")
    parser.add_argument("--unlock-all", action="store_true",
                        help="Patch ROM to unlock all levels from the start")
    parser.add_argument("--no-timer", action="store_true",
                        help="Freeze the in-game timer (always shows 00:00)")
    parser.add_argument("--analyze", action="store_true",
                        help="Print difficulty analysis of generated puzzles")
    parser.add_argument("--output-dir", default=OUTPUT_DIR,
                        help="Output directory for ROM and spoiler")
    args = parser.parse_args()

    # Load ROM
    with open(args.rom, "rb") as f:
        rom = f.read()
    rom_data = bytearray(rom)

    print(f"ROM: {args.rom} ({len(rom)} bytes)")

    # Parse all puzzles
    puzzles = read_all_puzzles(rom)
    print(f"Parsed {len(puzzles)} puzzles")

    sizes = {}
    for p in puzzles:
        sizes[p.size_name] = sizes.get(p.size_name, 0) + 1
    print(f"Sizes: {sizes}")

    new_grids = None

    if args.seed == 0:
        # Seed 0: dump existing puzzles, no modification
        print("\nSeed 0 — extracting original puzzles (no randomization)")
        spoiler_name = "picross_original_spoiler.txt"
    else:
        # Randomize
        rng = random.Random(args.seed)
        print(f"\nSeed {args.seed} — ", end="")

        if args.random_grids:
            mode = "easy (long runs)" if args.easy else "hard (scattered)"
            print(f"generating random grids — {mode} (density={args.density})")
            new_grids = randomize_all_grids(puzzles, rng, args.density,
                                            easy=args.easy)
        else:
            print("shuffling puzzles within size groups")
            new_grids = shuffle_puzzles(puzzles, rng)

        # Write modified solutions to ROM
        for p in puzzles:
            write_puzzle_solution(rom_data, p, new_grids[p.index])

        # Fix checksum
        fix_rom_checksum(rom_data)
        print("ROM checksum updated")

        spoiler_name = f"picross_randomized_{args.seed}_spoiler.txt"

    # Write outputs
    os.makedirs(args.output_dir, exist_ok=True)

    if args.seed == 0 and not args.unlock_all and not args.no_timer:
        # Seed 0 without unlock/patches: just write spoiler, no ROM needed
        rom_name = None
    else:
        if args.seed == 0:
            rom_name = "picross_unlocked.sfc"
        else:
            rom_name = f"picross_randomized_{args.seed}.sfc"

        rom_path = os.path.join(args.output_dir, rom_name)
        # Apply ROM patches
        if args.no_timer:
            apply_no_timer_patch(rom_data)
            fix_rom_checksum(rom_data)
            print("  ROM patched: timer frozen")

        if args.unlock_all:
            apply_unlock_rom_patch(rom_data)
            fix_rom_checksum(rom_data)
            print("  ROM patched: all levels unlocked")

        with open(rom_path, "wb") as f:
            f.write(rom_data)
        print(f"\nROM written: {rom_path}")

    spoiler_path = os.path.join(args.output_dir, spoiler_name)
    write_spoiler_log(spoiler_path, puzzles, new_grids)
    print(f"Spoiler written: {spoiler_path}")

    # Summary
    if new_grids:
        total_cells = sum(
            sum(cell for row in new_grids[p.index] for cell in row)
            for p in puzzles
        )
        print(f"\nTotal solution cells across all puzzles: {total_cells}")

    # Difficulty analysis
    if args.analyze:
        print_analysis(puzzles, new_grids)


if __name__ == "__main__":
    main()
