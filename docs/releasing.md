# Releasing

1. Update `py/core/version.py` (`VERSION = "x.y.z"`) and `CHANGELOG.md`; commit and push to `main`.
2. On GitHub: **Releases > Draft a new release**, create the tag `vx.y.z` (it must equal the version, with a leading `v`), write
   notes (or generate them) and **Publish**.
3. The `Release build` workflow (`.github/workflows/release.yml`) builds the firmware in the `espressif/idf:v5.5.4` container
   from the pinned sources (about 20-30 minutes) and attaches to the release:

| File | Use |
|---|---|
| `sigen-pydashboard-factory.bin` | blank or bricked board: `esptool write_flash 0x0` (bootloader + partitions + firmware + Python app; erases settings and history) |
| `sigen-pydashboard-ota.bin` | firmware update of a running board: `POST /api/ota` |
| `sigen-pydashboard-app.tar` | Python-app update of a running board: `POST /api/ota/py` (or `./scripts_ota.sh`) |
| `SHA256SUMS` | checksums |

The workflow fails early if the tag and `py/core/version.py` disagree. To test the build without publishing, run **Actions >
Release build > Run workflow**: the files come back as a build artifact.

How the factory image is made: `scripts/make_fs_image.py` writes a littlefs image of `py/` (the board's `vfs` partition,
0x5F0000), and `esptool merge_bin` places it, the bootloader, the partition table, `otadata` and the firmware into one 8 MB
file. The layout must match `board_s3_7/partitions.csv`.

To build the same files locally after `./build.sh`: `./make_factory.sh` (writes `dist/`, which is git-ignored).
