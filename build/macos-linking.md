# GAMBIT Link Performance on macOS / clang — Investigation

**Date:** 2026-06-12 · **Machine:** Apple M4 Pro, 14 cores, 24 GB RAM ·
**OS:** macOS 26.5 (Darwin 25.5.0) · **Toolchain:** Homebrew LLVM clang 22.1.7,
Apple linker `ld-1267` (Xcode 26.5 SDK), `ld64.lld` 22.1.7 available ·
**Build:** `build/` = Release (`-O3 -DNDEBUG`, no `-g`), Unix Makefiles, ccache

**问题（报告的症状）**：在 mac 上用 clang 构建时，最后的链接阶段极慢；构建完整 `gambit`
可执行文件时链接耗时可达 ~3 小时。正在尝试 lld。

## TL;DR

1. **实测：在当前工具链上，`gambit` 的最终 `ld` 调用本身只需 0.2 秒**（lld 0.7 秒）。
   重放 build 目录中记录的真实链接命令即可复现（方法见下）。所以 3 小时不是这条 `ld`
   命令在当前环境下的固有成本。
2. 链接命令里混入了 **`-Wl,-flat_namespace`** —— 它来自 Open MPI 的
   `MPI_Fortran_LINK_FLAGS`，被 `add_gambit_executable()` 误贴到所有 C++ 可执行文件上。
   该 flag 在旧版 Apple linker（Xcode 15/16 时代）上对大型 C++ 链接有**病态级别的减速**
   （已知问题，Apple 已弃用此 flag），高度怀疑是历史上 3 小时链接的元凶。
3. 第二嫌疑：`make -j14` 在 24 GB 内存上的**内存压力/换页**。GAMBIT 的巨型编译单元
   （`gambit.cpp.o` 46 MB、`solo.cpp.o` 23 MB）编译时各占数 GB；链接与这些编译并发时
   机器进入 swap 颠簸，链接器表现为"挂住几小时"。
4. 修复建议（按优先级）：过滤 `flat_namespace`；全局启用 lld（不只是 CBS）；限制并发
   `-j`；保持 Release/`-g0`。

---

## 1. How GAMBIT links (structure)

- Each Bit (ColliderBit, DarkBit, …) and each common component (Logs, Utils, Models,
  Backends, Elements, Printers, Core) is a CMake **object library**.
- The `gambit` executable links `Core/src/gambit.cpp` + *every object file of every
  enabled component* directly (no static archives) — see
  [cmake/executables.cmake](../../../cmake/executables.cmake) and
  `add_gambit_executable()` in [cmake/utilities.cmake:319](../../../cmake/utilities.cmake).
  Object lists (not archives) are **by design**: GAMBIT relies on static-initializer
  self-registration (rollcall/functor machinery), which archive lazy-extraction would break.
- Standalones (CBS, etc.) re-link the full module object lists + common objects each —
  `add_standalone()` in [cmake/utilities.cmake:407](../../../cmake/utilities.cmake).
- Current numbers (this checkout, Release): **477 object files, ~400 MB inputs,
  65 MB output binary, ~348k symbol-table entries** (≈45k weak). Large but not extreme.

## 2. The smoking gun: `-Wl,-flat_namespace`

The recorded link command (`build/CMakeFiles/gambit.dir/link.txt`) contains
`-Wl,-flat_namespace`. Origin:

```
build/CMakeCache.txt:
  MPI_CXX_LINK_FLAGS:      (empty)
  MPI_C_LINK_FLAGS:        (empty)
  MPI_Fortran_LINK_FLAGS:  -Wl,-flat_namespace      <- Open MPI's Fortran wrapper flags
```

In `add_gambit_executable()` ([cmake/utilities.cmake:337-354](../../../cmake/utilities.cmake))
the three MPI blocks each do `set_target_properties(... LINK_FLAGS ...)`. The property is
**overwritten, not appended**, so the Fortran flags win and every GAMBIT executable links
with `-flat_namespace` — a Fortran-app workaround that GAMBIT's C++ executables do not need.

Why this matters: `-flat_namespace` disables macOS two-level namespace binding. On older
Apple linkers (classic `ld64`, and early `ld-prime` in Xcode 15/16) flat-namespace links of
large C++ binaries degenerate badly (symbol lookup effectively linear over all dylibs ×
symbols; several projects reported minutes→hours regressions). Apple deprecates the flag.
It also changes *runtime* dyld semantics (symbol interposition across all images).

On the **current** `ld-1267` the pathology appears fixed (see measurements), but the flag
remains a latent footgun for every collaborator on an older Xcode — and it is simply wrong
to apply it.

## 3. Measurements (2026-06-12)

Replaying the exact recorded link command on an otherwise idle machine
(method: `sed` the `-o` target in `link.txt`, run with `/usr/bin/time -p`):

| Variant | Linker | Wall time | Result |
|---|---|---|---|
| A: recorded command, with `-flat_namespace` | Apple ld-1267 | **0.20 s** | 65 MB binary, OK |
| B: same minus `-flat_namespace` | Apple ld-1267 | **0.23 s** | OK |
| C: same minus flag, `-fuse-ld=lld` | ld64.lld 22.1.7 | **0.68 s** | OK |

Conclusions:

- The final `ld` invocation is **not** the current bottleneck — both Apple ld and lld are
  sub-second on this link.
- Therefore the observed 3 h must have come from a different *state*: older toolchain
  (the older `build_gambit.sh` used `llvm@19` + RelWithDebInfo on an earlier Xcode —
  exactly the era of the flat-namespace pathology), and/or system memory pressure
  (below), and/or `-g` builds inflating I/O.

### The memory-pressure scenario

`make -j14` on a 24 GB machine: near the end of a build the largest TUs compile
concurrently (each of `gambit.cpp`, `solo.cpp`, functor TUs can hold multiple GB of
clang RSS) just as the link starts mapping ~400 MB of objects. Once the machine starts
swapping, *everything* — including a normally sub-second link — can take hours, and `make`
shows it sitting at "Linking CXX executable gambit". This matches the reported symptom and
is toolchain-independent.

**Diagnostic next time it happens:** while the link "hangs", run
`vm_stat 5` (watch pageouts), `top -o mem`, and `sample <ld-pid> 5` — this distinguishes
swap-thrash (pageouts climbing) from genuine linker pathology (ld at 100% CPU, no paging).

## 4. Recommendations

### 4.1 Stop `-flat_namespace` leaking into executables (do this regardless)

In `add_gambit_executable()` either drop the Fortran block for CXX targets or filter the flag:

```cmake
if(MPI_Fortran_FOUND AND MPI_Fortran_LINK_FLAGS)
  string(REPLACE "-Wl,-flat_namespace" "" _mpi_f_link "${MPI_Fortran_LINK_FLAGS}")
  string(STRIP "${_mpi_f_link}" _mpi_f_link)
  if(_mpi_f_link)
    set_property(TARGET ${executablename} APPEND_STRING PROPERTY LINK_FLAGS " ${_mpi_f_link}")
  endif()
endif()
```

(Also note the pre-existing bug: the three `set_target_properties(LINK_FLAGS)` calls
overwrite each other; if CXX/C MPI flags are ever non-empty they are silently lost.
`APPEND_STRING` as above fixes both.)

### 4.2 Adopt lld globally (robust against old Apple linkers)

The current `GAMBIT_USE_LLD_FOR_CBS` option (uncommitted, `cmake/standalones.cmake`) only
covers the CBS target. Generalise — at configure time:

```bash
-DCMAKE_EXE_LINKER_FLAGS="-fuse-ld=lld ..." \
-DCMAKE_SHARED_LINKER_FLAGS="-fuse-ld=lld ..." \
-DCMAKE_MODULE_LINKER_FLAGS="-fuse-ld=lld ..."
```

or in CMake (≥3.29 also supports `CMAKE_LINKER_TYPE=LLD`):

```cmake
option(GAMBIT_USE_LLD "Link all GAMBIT targets with lld" OFF)
if(GAMBIT_USE_LLD)
  add_link_options(-fuse-ld=lld)
endif()
```

Homebrew LLVM ships `ld64.lld`; clang resolves `-fuse-ld=lld` to it automatically.
Measured cost on this machine: none that matters (0.68 s vs 0.20 s — both negligible).
Benefit: immunity to Apple-linker regressions, identical behaviour for all collaborators.

### 4.3 Tame peak memory during builds

- `make -j8` (not `-j14`) on 24 GB; or split: `make -j14 ColliderBit && make -j4 gambit`.
- Keep Release / `-g0` for routine work (the presets already do this); use RelWithDebInfo
  only when actually debugging.
- ccache is already configured in the presets — keep it.

### 4.4 Structural observations (longer term, optional)

- Link inputs are dominated by a few giant TUs (`gambit.cpp.o` 46 MB — it instantiates
  every rollcall; `Core/functors.cpp.o`, `functors_for_CBS.cpp.o`). These cost *compile*
  time/memory, not link time. Splitting the per-Bit rollcall instantiations into separate
  TUs would smooth peak RAM and improve incremental rebuilds.
- The object-library (no archive) link model is required by static-initializer
  registration; do not "optimise" it into static archives without `-all_load` semantics.
- `ld` warning `ignoring duplicate libraries: '-lgfortran', '-lomp'` is cosmetic
  (flags injected both by `CMAKE_EXE_LINKER_FLAGS` and the library lists); harmless.

## 5. Reproduction commands

```bash
cd build
# replay recorded link with timing (writes /tmp/gambit_link_test)
sed 's| -o .*gambit | -o /tmp/gambit_link_test |' CMakeFiles/gambit.dir/link.txt > /tmp/L.sh
/usr/bin/time -p sh /tmp/L.sh
# variant without flat_namespace
sed 's| -Wl,-flat_namespace | |' /tmp/L.sh > /tmp/L2.sh && /usr/bin/time -p sh /tmp/L2.sh
# variant with lld
sed 's| -o | -fuse-ld=lld -o |' /tmp/L2.sh > /tmp/L3.sh && /usr/bin/time -p sh /tmp/L3.sh
```

## 6. Open questions / follow-ups

- [ ] Reproduce a slow link once more under a full `make -j14` and capture `vm_stat` —
      confirms or kills the memory-pressure hypothesis on the current toolchain.
- [ ] Decide: upstream a `GAMBIT_USE_LLD` global option + the flat_namespace filter
      (both are small patches to `cmake/utilities.cmake` / `standalones.cmake`).
- [ ] Check whether the Linux/HPC builds also receive unwanted Fortran MPI link flags
      (same code path; Linux Open MPI usually has empty Fortran link flags, but verify).
