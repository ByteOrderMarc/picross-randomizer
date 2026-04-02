"""
Mario's Super Picross — ROM Data Parser
=========================================

Reads and writes puzzle data from/to the ROM file.

ROM Layout (HiROM + FastROM):
  - Pointer table at file offset 0xC931 (SNES $C0:C931)
    302 entries x 4 bytes: [offset_lo, offset_hi, bank, 0x00]
  - Puzzle data in banks $CA-$CC (file offsets 0xA0000-0xCCD3E)
  - Each puzzle is a tagged-block structure

Tagged Block Format:
  Each block starts with a tag byte, followed by a 16-bit LE skip value,
  then payload data. Next block is at (tag_offset + 1) + skip_value.

  Tag 0x00: Metadata (6 bytes). Byte 0 = grid size code:
            0=5x5, 1=10x10, 2=15x15, 3=20x20, 6=25x20
  Tag 0x01: Solution bitfield. LSB-first bit stream, one bit per cell,
            row-major order. This is what we modify for randomization.
  Tag 0x02: Per-cell display attributes (4 bits/cell, reveal image colors)
  Tag 0x03: Tilemap data for reveal animation
  Tag 0x04: Sub-puzzle configuration
  Tag 0x05: Additional metadata (optional)
  Tag 0xFF: End-of-block marker

Solution Encoding:
  Bits are packed LSB-first into bytes. For a WxH grid, the bitfield
  is ceil(W*H / 8) bytes. The game's loader at SNES $C0:15A3 uses LSR
  to extract bits and ROL to place them into the WRAM grid at $1234.

Level Structure:
  Mario mode: 13 levels, puzzle indices 0-144
    Levels 0-11: 12 puzzles each (144 total), Level 12: 1 puzzle
  Wario mode: 13 levels, puzzle indices 145-301
    Levels 0-10: 12 each, Level 11: 8, Level 12: 17

  Level start tables in ROM:
    Mario: SNES $C0:EB09 (file 0xEB09)
    Wario: SNES $C0:EB23 (file 0xEB23)
"""

import math
from dataclasses import dataclass

# ROM constants
POINTER_TABLE_OFFSET = 0xC931
POINTER_TABLE_ENTRIES = 302
POINTER_ENTRY_SIZE = 4

# HiROM address conversion: SNES bank $CA = file offset 0xA0000
# Formula: file_offset = ((bank - 0xC0) * 0x10000) + address_within_bank
# For pointer entries: file_offset = ((bank - 0xC0) << 16) | (hi << 8) | lo

# Grid size codes -> (columns, rows)
GRID_SIZE_MAP = {
    0: (5, 5),
    1: (10, 10),
    2: (15, 15),
    3: (20, 20),
    6: (25, 20),
}

# Level structure
MARIO_LEVELS = 13   # 0-11 have 12 puzzles, level 12 has 1
WARIO_LEVELS = 13   # 0-10 have 12 each, level 11 has 8, level 12 has 17
MARIO_START_INDEX = 0
WARIO_START_INDEX = 145


@dataclass
class Puzzle:
    """A single picross puzzle extracted from ROM."""
    index: int              # Puzzle index (0-301)
    cols: int               # Grid width
    rows: int               # Grid height
    grid: list              # 2D list of bools (True = filled)
    rom_offset: int         # File offset of tag 0x01 payload
    bitfield_size: int      # Size of solution bitfield in bytes
    mode: str               # "mario" or "wario"
    level: int              # Level number within mode
    position: int           # Position within level

    @property
    def size_name(self):
        return f"{self.cols}x{self.rows}"

    @property
    def solution_count(self):
        return sum(cell for row in self.grid for cell in row)

    def to_ascii(self):
        """Render puzzle solution as ASCII art."""
        lines = []
        lines.append(f"Puzzle {self.index} ({self.mode} L{self.level}-{self.position}) "
                      f"[{self.size_name}, {self.solution_count} cells]")
        for row in self.grid:
            lines.append("  " + " ".join("#" if c else "." for c in row))
        return "\n".join(lines)


def snes_to_file_offset(bank, hi, lo):
    """Convert SNES HiROM address components to file offset."""
    return ((bank - 0xC0) << 16) | (hi << 8) | lo


def read_pointer_table(rom):
    """Read the 302-entry puzzle pointer table."""
    pointers = []
    for i in range(POINTER_TABLE_ENTRIES):
        offset = POINTER_TABLE_OFFSET + i * POINTER_ENTRY_SIZE
        lo = rom[offset]
        hi = rom[offset + 1]
        bank = rom[offset + 2]
        file_off = snes_to_file_offset(bank, hi, lo)
        pointers.append(file_off)
    return pointers


def parse_tagged_blocks(rom, file_offset):
    """Parse tagged blocks at a puzzle's ROM location.

    Returns dict of {tag: [(payload_offset, payload_size), ...]}
    """
    blocks = {}
    pos = file_offset

    while pos < len(rom):
        tag = rom[pos]
        if tag == 0xFF:
            break

        # 16-bit LE skip value
        skip = rom[pos + 1] | (rom[pos + 2] << 8)
        payload_offset = pos + 3
        payload_size = skip - 2  # skip includes the 2 skip bytes

        if tag not in blocks:
            blocks[tag] = []
        blocks[tag].append((payload_offset, payload_size))

        # Next block
        pos = (pos + 1) + skip

    return blocks


def decode_solution_bitfield(rom, offset, size, cols, rows):
    """Decode LSB-first packed bitfield into a 2D grid of bools."""
    total_cells = cols * rows
    grid = []
    bit_index = 0

    for r in range(rows):
        row = []
        for c in range(cols):
            byte_idx = bit_index // 8
            bit_pos = bit_index % 8
            if byte_idx < size:
                bit = (rom[offset + byte_idx] >> bit_pos) & 1
            else:
                bit = 0
            row.append(bool(bit))
            bit_index += 1
        grid.append(row)

    return grid


def encode_solution_bitfield(grid, cols, rows):
    """Encode a 2D grid of bools into LSB-first packed bitfield bytes."""
    total_cells = cols * rows
    num_bytes = math.ceil(total_cells / 8)
    data = bytearray(num_bytes)
    bit_index = 0

    for r in range(rows):
        for c in range(cols):
            if grid[r][c]:
                byte_idx = bit_index // 8
                bit_pos = bit_index % 8
                data[byte_idx] |= (1 << bit_pos)
            bit_index += 1

    return bytes(data)


def get_puzzle_mode_and_level(index):
    """Determine mode, level, and position for a puzzle index."""
    if index < WARIO_START_INDEX:
        mode = "mario"
        remaining = index
        for level in range(MARIO_LEVELS):
            if level < 12:
                count = 12
            else:
                count = 1
            if remaining < count:
                return mode, level, remaining
            remaining -= count
    else:
        mode = "wario"
        remaining = index - WARIO_START_INDEX
        for level in range(WARIO_LEVELS):
            if level < 11:
                count = 12
            elif level == 11:
                count = 8
            else:
                count = 17
            if remaining < count:
                return mode, level, remaining
            remaining -= count

    return "unknown", 0, index


def read_puzzle(rom, index, pointer):
    """Read a single puzzle from ROM."""
    blocks = parse_tagged_blocks(rom, pointer)

    # Tag 0x00: metadata
    if 0x00 not in blocks:
        return None
    meta_offset, meta_size = blocks[0x00][0]
    size_code = rom[meta_offset]
    if size_code not in GRID_SIZE_MAP:
        return None
    cols, rows = GRID_SIZE_MAP[size_code]

    # Tag 0x01: solution bitfield
    if 0x01 not in blocks:
        return None
    sol_offset, sol_size = blocks[0x01][0]
    grid = decode_solution_bitfield(rom, sol_offset, sol_size, cols, rows)

    mode, level, position = get_puzzle_mode_and_level(index)

    return Puzzle(
        index=index,
        cols=cols,
        rows=rows,
        grid=grid,
        rom_offset=sol_offset,
        bitfield_size=sol_size,
        mode=mode,
        level=level,
        position=position,
    )


def read_all_puzzles(rom):
    """Read all 302 puzzles from ROM."""
    pointers = read_pointer_table(rom)
    puzzles = []
    for i, ptr in enumerate(pointers):
        puzzle = read_puzzle(rom, i, ptr)
        if puzzle:
            puzzles.append(puzzle)
    return puzzles


def write_puzzle_solution(rom_data, puzzle, new_grid):
    """Write a new solution grid into the ROM bytearray.

    Only modifies the tag 0x01 bitfield bytes. The game recomputes
    clue numbers at runtime, so no other changes are needed.
    """
    encoded = encode_solution_bitfield(new_grid, puzzle.cols, puzzle.rows)
    assert len(encoded) == puzzle.bitfield_size, \
        f"Encoded size {len(encoded)} != expected {puzzle.bitfield_size}"
    rom_data[puzzle.rom_offset:puzzle.rom_offset + puzzle.bitfield_size] = encoded


def fix_rom_checksum(rom_data):
    """Recalculate and write the SNES internal checksum.

    HiROM checksum location: file offset 0xFFDE-0xFFDF (checksum)
    and 0xFFDC-0xFFDD (complement).
    Note: HiROM uses $FFDC, NOT $7FDC (which is LoROM).
    """
    # Zero out existing checksum fields
    rom_data[0xFFDC] = 0
    rom_data[0xFFDD] = 0
    rom_data[0xFFDE] = 0
    rom_data[0xFFDF] = 0

    # Sum all bytes
    checksum = sum(rom_data) & 0xFFFF
    complement = checksum ^ 0xFFFF

    # Write back
    rom_data[0xFFDC] = complement & 0xFF
    rom_data[0xFFDD] = (complement >> 8) & 0xFF
    rom_data[0xFFDE] = checksum & 0xFF
    rom_data[0xFFDF] = (checksum >> 8) & 0xFF
