# Mario's Super Picross — ROM Format Documentation

## Overview

- **Platform**: Super Famicom (SNES)
- **ROM mapping**: HiROM + FastROM (header byte at $FFD5 = 0x31)
- **ROM size**: 1MB (1,048,576 bytes)
- **Publisher**: Nintendo / Jupiter (1995, Japan only)
- **Total puzzles**: 302

## Address Conversion

HiROM mapping: SNES bank `$C0` = file offset `0x00000`.

```
file_offset = ((bank - 0xC0) << 16) | address_within_bank
```

Example: SNES `$CA:1234` = file offset `((0xCA - 0xC0) << 16) | 0x1234` = `0xA1234`.

## Puzzle Pointer Table

**Location**: File offset `0xC931` (SNES `$C0:C931`)

302 entries, 4 bytes each:

| Offset | Size | Description |
|--------|------|-------------|
| +0 | 1 | Address low byte |
| +1 | 1 | Address high byte |
| +2 | 1 | Bank byte |
| +3 | 1 | Always 0x00 (padding) |

Total table size: 302 × 4 = 1,208 bytes (ends at `0xCDE9`).

Each entry points to a puzzle's tagged block data in banks `$CA`–`$CC`
(file range `0xA0000`–`0xCCD3E`).

## Tagged Block Format

Each puzzle is stored as a sequence of tagged blocks. Navigation:

```
tag_byte | skip_lo | skip_hi | payload...
```

- `tag_byte`: block type identifier
- `skip_lo/hi`: 16-bit LE value. Next block starts at `(tag_offset + 1) + skip_value`
- `payload`: block data, size = `skip_value - 2`

### Tag Types

| Tag | Count | Description |
|-----|-------|-------------|
| `0x00` | 1 | **Metadata**. 6 bytes. Byte 0 = grid size code |
| `0x01` | 1 | **Solution bitfield**. Packed bits, LSB-first, row-major |
| `0x02` | 1–8 | **Display attributes**. 4 bits per cell (reveal image colors) |
| `0x03` | 1–8 | **Tilemap data**. 33 bytes each (reveal animation) |
| `0x04` | 1 | **Sub-puzzle config**. Variable size |
| `0x05` | 0–1 | **Extra metadata**. Optional, present for ~126 puzzles |
| `0xFF` | 1 | **End marker**. No payload |

### Grid Size Codes (Tag 0x00, byte 0)

| Code | Grid Size | Cells | Puzzles |
|------|-----------|-------|---------|
| 0 | 5×5 | 25 | 5 |
| 1 | 10×10 | 100 | 20 |
| 2 | 15×15 | 225 | 118 |
| 3 | 20×20 | 400 | 110 |
| 6 | 25×20 | 500 | 49 |

## Solution Bitfield (Tag 0x01)

The puzzle solution is stored as a packed bit stream:

- **Bit order**: LSB-first within each byte
- **Cell order**: Row-major (left-to-right, top-to-bottom)
- **Size**: `ceil(cols × rows / 8)` bytes
- **Encoding**: 1 = filled cell, 0 = empty cell

### Example: 5×5 puzzle with 13 cells

Solution grid:
```
# # # # #   → bits: 1 1 1 1 1
. . . # #   → bits: 0 0 0 1 1
. . # # .   → bits: 0 0 1 1 0
. # # . .   → bits: 0 1 1 0 0
. . # # .   → bits: 0 0 1 1 0
```

Packed LSB-first:
```
Byte 0: bits 0-7  = 1,1,1,1,1,0,0,0 = 0x1F
Byte 1: bits 8-15 = 1,1,0,0,1,1,0,0 = 0x33
Byte 2: bits 16-23 = 1,1,0,0,0,0,1,1 = 0xC3
Byte 3: bits 24-25 = 0,0,xxxxxx       = 0x00
```

### Loader Routine

The game's solution loader at SNES `$C0:15A3` reads the bitfield using
`LSR` to extract bits from each source byte and `ROL $1234,X` to place
them into the WRAM grid buffer. Each cell in the WRAM grid at `$7E:1234`
is one byte, with bit 0 indicating whether the cell is part of the solution.

### Clue Number Computation

**Row and column clue numbers are computed at runtime** by the routine at
SNES `$C0:15DB`. This scans the loaded grid after the solution bitfield
is unpacked. Therefore, modifying only the tag 0x01 data is sufficient
for randomization — the displayed clue numbers will automatically match
the new solution.

## Level Structure

### Mario Mode (Indices 0–144)

| Level | Puzzles | Index Range |
|-------|---------|-------------|
| 1–12 | 12 each | 0–143 |
| 13 (Special) | 1 | 144 |

**Total**: 145 puzzles

### Wario Mode (Indices 145–301)

| Level | Puzzles | Index Range |
|-------|---------|-------------|
| 1–11 | 12 each | 145–276 |
| 12 (Ultra) | 8 | 277–284 |
| 13 (EX) | 17 | 285–301 |

**Total**: 157 puzzles

### Level Start Tables

- **Mario**: SNES `$C0:EB09` (file `0xEB09`)
- **Wario**: SNES `$C0:EB23` (file `0xEB23`)

The level mapping routine at SNES `$C0:AF09` computes:
```
puzzle_index = level_start_table[level_number] + position_within_level
```

## WRAM Layout (Runtime)

Key addresses during gameplay (relative to `$7E0000`):

| Address | Size | Description |
|---------|------|-------------|
| `$1234` | 32 bytes/row | Puzzle grid buffer (1 byte/cell, bit 0 = solution) |
| `$1102` | 2 | Remaining cells counter (16-bit LE) |
| `$1104` | 2 | Remaining cells counter (mirror) |
| `$11D2` | 1 | Cursor column (X) |
| `$11D6` | 1 | Cursor row (Y) |
| `$119C` | 1 | Screen mode (0x07 = puzzle gameplay) |
| `$0FDE` | 1 | Timer frame counter |
| `$0FE4` | 1 | Timer minutes |

Grid buffer stride is `0x20` (32) bytes per row, supporting up to 25 columns.
Maximum grid dimensions: 25 columns × 20 rows.

## Save Data (SRAM)

- **Size**: 8KB
- **HiROM location**: Banks `$20`–`$3F`, offset `$6000`–`$7FFF`
- **Initialization**: ROM bank `$C4` (file offset `0x40000`+) contains
  default save data, copied to WRAM `$3600`–`$4E00` on new game

Level unlock flags are stored as bitfields within the save buffer.
Completion is tracked per-puzzle; clearing all puzzles in a level
unlocks the next one.

## ROM Checksum

| File Offset | SNES Address | Description |
|-------------|--------------|-------------|
| `0xFFDC` | `$C0:FFDC` | Checksum complement (16-bit LE) |
| `0xFFDE` | `$C0:FFDE` | Checksum (16-bit LE) |

Checksum = sum of all ROM bytes (mod 0x10000), with checksum fields
zeroed before computation. Complement = checksum XOR 0xFFFF.

## Compression

The game uses LZ1-like compression for **graphics data only** (not puzzles).
Decompression routine at SNES `$C0:1939` handles five command types:
Direct Copy, Byte Fill, Word Fill, Increase Fill, and Repeat.
Decompressed data targets bank `$7F` (high WRAM).

Puzzle solution data (tag 0x01) is **not compressed** — it's a raw bitfield.
