#!/usr/bin/env python3
r"""CAD EPSG Converter | Version 1.0 | single-file Windows GUI and CLI.

Reproject DXF/DWG model-space geometry between the 39 EPSG systems in
EPSG_SYSTEMS. The default is Datum 73 / Modified Portuguese Grid (27493) to
ETRS89 / Portugal TM06 (3763). DXF uses ezdxf; DWG additionally requires the
separately installed ODA File Converter. Inputs are never modified.

Coordinate contract
-------------------
Projected XY: easting/northing in metres. Geographic XY: Greenwich longitude /
latitude in decimal degrees, not latitude/longitude. EPSG:2963 and EPSG:5017
are the documented exceptions: X=southing, Y=westing. Geocentric XYZ are all
metres and require compatible ellipsoidal height. Ordinary horizontal conversions preserve Z by
default; horizontal NTv2 grids do not transform vertical datums or epochs.

Historical mainland datum changes require the matching validated NTv2 grid:
    Datum 73:    pt73_e89.gsb (renamed DGT grid)
    Lisbon:      ptLX_e89.gsb (renamed DGT grid)
    ED50:        ptED_e89.gsb
    Lisbon 1890: ptLB_e89.gsb
Names are case-insensitive. The canonical pt*_e89.gsb names take priority within a folder.
An explicitly selected grid folder is exclusive. Otherwise external files beside
the executable/script take priority over bundled files. Source/target datum,
ellipsoid axes, all subgrids and all nodes are checked; actual hashes are reported.
Missing or incompatible mandatory grids are fatal. Out-of-grid objects are skipped
and reported by default; --stop-outside-grid or --strict disables that cleanup.
Other PROJ stages require the best locally available operation unless degradation
is explicitly allowed; network downloads and ballpark transformations are off by default.

Geometry and verification
-------------------------
Native coordinates are transformed in WCS, without a constant metres/degree
factor. True circular arcs, polylines and native spline/ellipse evaluators are
sampled with a source sagitta of 0.01 m or 1e-8 degree by default. Straight source
edges are additionally refined against a 0.01 m target-chord criterion. Widths
use local direction-dependent perpendicular scales; extended text, patterns and
opaque solids remain explicitly reported local approximations. These controls
are not a global survey-accuracy guarantee. Historical-grid/geocentric pairs
without a height-datum model are rejected rather than inventing target heights.

Blocks, dimensions, multileaders and supported proxy graphics become native
display geometry. Best effort omits failed CAD objects and reports their handles;
--strict blocks publication for identified unresolved objects. Out-of-grid cleanup
removes complete failed leaves, not selected polyline vertices, and records their
source handles. In-coverage (0,0,0) coordinates are retained. No datum fallback or
extrapolation is substituted for a mandatory grid. Outputs receive a fitted WCS
model-space view and are reopened, audited and checked against their exposed
native target coordinates. Saved-position verification follows active text
alignment. Closed straight hatch loops may omit a terminal closing point only
when both its own closure and its match to the other loop's start are within
0.00001 m; every remaining point is still verified. No degree-sized tolerance,
interior vertex removal or unverified hatch omission is used.
Raster/OLE payloads, external files and opaque application coordinates are not
independently warped. Keep original drawings, reports and surveyed controls.

Windows Command Prompt quick start (Python with Tcl/Tk)
----------------------------------------------------------
    py -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    python -m pip install "ezdxf==1.4.4" "pyproj==3.7.2" "Pillow>=12,<13"
    python script.py

Run without inputs for the GUI. Example CLI:
    python script.py drawing.dxf --output-dir output --grid-dir .
    python script.py drawing.dxf --source-epsg 4326 --target-epsg 3763 --output-dir output
    python script.py --help

Source syntax and version checks:
    python -m py_compile script.py
    python script.py --version

PyInstaller creates an executable; py_compile only checks Python syntax:
    python -m pip install --upgrade "PyInstaller>=6.15,<7" pyinstaller-hooks-contrib
    python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name script --collect-all ezdxf --collect-all pyproj --collect-all PIL --collect-all fontTools --add-data "pt73_e89.gsb;." --add-data "ptLX_e89.gsb;." --add-data "ptED_e89.gsb;." --add-data "ptLB_e89.gsb;." script.py

See README.md for the complete theory, accuracy limits, grid provenance,
installation, PowerShell activation, compilation and clean-Windows acceptance
procedure. Replacing script.py does not update an existing script.exe.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import math
import os
import queue
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import warnings
from collections import Counter, OrderedDict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

APP_NAME = "CAD EPSG Converter"
APP_VERSION = "1.0"
DEFAULT_SOURCE_EPSG = 27493
DEFAULT_TARGET_EPSG = 3763
DEFAULT_CURVE_TOLERANCE = 0.01
DEFAULT_ANGULAR_CURVE_TOLERANCE = 1e-8
DEFAULT_REPROJECTION_TOLERANCE_M = 0.01
MAX_CURVE_VERTICES = 1_000_000
DEFAULT_DWG_TIMEOUT = 900
POINT_CACHE_LIMIT = 65_536
MATRIX_CACHE_LIMIT = 8_192
TRANSFORM_BATCH_SIZE = 4_096
EDGE_CACHE_LIMIT = 4_096
OMISSION_LOG_LIMIT = 20


# Supported CRS identifiers and descriptive labels shown in both selectors.
EPSG_SYSTEMS: tuple[tuple[int, str], ...] = (
    # =========================================================================
    # GLOBAL / WEB STANDARDS (INTEROPERABILITY LAYER)
    # =========================================================================
    # Geographic CAD XY is longitude/latitude, in decimal degrees.
    (4326, "WGS 84 / Geographic 2D"),
    (3857, "WGS 84 / Pseudo-Mercator"),
    # WGS 84 UTM grids: mainland, Madeira, central/eastern and western Azores.
    (32629, "WGS 84 / UTM zone 29N"),
    (32628, "WGS 84 / UTM zone 28N"),
    (32626, "WGS 84 / UTM zone 26N"),
    (32625, "WGS 84 / UTM zone 25N"),

    # =========================================================================
    # MAINLAND PORTUGAL
    # =========================================================================
    # ETRS89 geographic, geocentric and projected representations.
    (4258, "ETRS89 / Geographic 2D"),
    (4937, "ETRS89 / Geographic 3D"),
    (4936, "ETRS89 / Geocentric coordinates"),
    (3763, "ETRS89 / Portugal TM06"),
    (25829, "ETRS89 / UTM zone 29N"),
    # Historical datums and grids (Datum 73, Lisbon and ED50).
    (4274, "Datum 73 / Geographic 2D"),
    (27493, "Datum 73 / Modified Portuguese Grid"),
    (4207, "Lisbon / Geographic 2D"),
    # The following two projected CRSs retain the Lisbon prime meridian.
    (20790, "Lisbon / Portuguese National Grid"),
    (20791, "Lisbon / Portuguese Grid"),
    (5018, "Lisbon / Portuguese Grid New"),
    (4666, "Lisbon 1890 / Geographic 2D"),
    # Both Bonne definitions use CAD X=southing (P), Y=westing (M).
    # 2963 references the Lisbon meridian; 5017 references Greenwich.
    (2963, "Lisbon 1890 / Portugal Bonne (X=South, Y=West)"),
    (5017, "Lisbon 1890 / Portugal Bonne New (X=South, Y=West)"),
    (4230, "ED50 / Geographic 2D"),
    (23029, "ED50 / UTM zone 29N"),

    # =========================================================================
    # AZORES ARCHIPELAGO / SHARED PTRA08 REPRESENTATIONS
    # =========================================================================
    # These three PTRA08 CRS definitions also cover MADEIRA.
    # Geographic 3D requires ellipsoidal height; geocentric requires ECEF XYZ.
    (5013, "PTRA08 / Geographic 2D"),
    (5012, "PTRA08 / Geographic 3D"),
    (5011, "PTRA08 / Geocentric coordinates"),
    (5014, "PTRA08 / UTM zone 25N"),
    (5015, "PTRA08 / UTM zone 26N"),
    # Regional 1995 datums, distinct from PTRA08.
    (4664, "Azores Oriental 1995 / Geographic 2D"),
    (3062, "Azores Oriental 1995 / UTM zone 26N"),
    (4665, "Azores Central 1995 / Geographic 2D"),
    (3063, "Azores Central 1995 / UTM zone 26N"),
    # Historical local datums.
    (2188, "Azores Occidental 1939 / UTM zone 25N"),
    (2189, "Azores Central 1948 / UTM zone 26N"),
    (2190, "Azores Oriental 1940 / UTM zone 26N"),

    # =========================================================================
    # MADEIRA ARCHIPELAGO
    # =========================================================================
    # Geographic/geocentric PTRA08: use shared 5013/5012/5011 above.
    (5016, "PTRA08 / UTM zone 28N"),
    # ETRS89 is a different datum, not an alias for PTRA08.
    (25828, "ETRS89 / UTM zone 28N"),
    (4663, "Porto Santo 1995 / Geographic 2D"),
    (3061, "Porto Santo 1995 / UTM zone 28N"),
    (2942, "Porto Santo / UTM zone 28N"),
)

EPSG_LABELS = tuple(f"EPSG:{code} — {name}" for code, name in EPSG_SYSTEMS)
EPSG_NAME_BY_CODE = dict(EPSG_SYSTEMS)
SOUTH_WEST_EPSG_CODES = frozenset({2963, 5017})
WGS84_EPSG_CODES = frozenset({4326, 3857, 32629, 32628, 32626, 32625})


try:
    import ezdxf
    from ezdxf import bbox as ezdxf_bbox
    from ezdxf import recover as ezdxf_recover
    from ezdxf.math import Matrix44, Vec3
    from ezdxf.path import from_hatch as paths_from_hatch
    from ezdxf.path import make_path
except Exception as exc:  # pragma: no cover - shown in the GUI
    ezdxf = None  # type: ignore[assignment]
    ezdxf_recover = None  # type: ignore[assignment]
    ezdxf_bbox = None  # type: ignore[assignment]
    Matrix44 = None  # type: ignore[assignment,misc]
    Vec3 = None  # type: ignore[assignment,misc]
    paths_from_hatch = None  # type: ignore[assignment]
    make_path = None  # type: ignore[assignment]
    EZDXF_IMPORT_ERROR = str(exc)
else:
    EZDXF_IMPORT_ERROR = ""

try:
    import pyproj
    from pyproj import CRS, Transformer, database, network
    from pyproj.aoi import AreaOfInterest
    from pyproj.transformer import TransformerGroup
except Exception as exc:  # pragma: no cover - shown in the GUI
    CRS = None  # type: ignore[assignment,misc]
    Transformer = None  # type: ignore[assignment]
    TransformerGroup = None  # type: ignore[assignment]
    pyproj = AreaOfInterest = database = network = None
    PYPROJ_IMPORT_ERROR = str(exc)
else:
    PYPROJ_IMPORT_ERROR = ""

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except Exception as exc:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    filedialog = messagebox = ttk = ScrolledText = None  # type: ignore[assignment]
    TK_IMPORT_ERROR = str(exc)
else:
    TK_IMPORT_ERROR = ""


class ConversionError(RuntimeError):
    """A conversion error that can be shown directly to the user."""

    def __init__(
        self, message: str, *, file_result: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.file_result = file_result


class CancelledError(ConversionError):
    """Raised after a cooperative cancellation request."""


class CoordinateTransformationError(ConversionError):
    """A coordinate-operation failure; only typed domain skips are recoverable."""


class GridCoverageError(CoordinateTransformationError):
    """A real grid-domain failure, carrying the point in the grid's source datum."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class CancellationToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self._event.is_set():
            raise CancelledError("Conversion cancelled by the user.")

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class ConversionJob:
    input_paths: tuple[str, ...]
    output_directory: str
    source_epsg: int = DEFAULT_SOURCE_EPSG
    target_epsg: int = DEFAULT_TARGET_EPSG
    output_format: str = "dxf"  # dxf | dwg
    output_suffix: str = "_EPSG3763"
    curve_tolerance: float | None = None
    reprojection_tolerance_m: float = DEFAULT_REPROJECTION_TOLERANCE_M
    preserve_z: bool = True
    transform_paper_space: bool = False
    strict_unresolved: bool = False
    allow_ballpark: bool = False
    allow_degraded: bool = False
    overwrite: bool = False
    audit_and_recover: bool = True
    oda_executable: str | None = None
    dwg_timeout_seconds: int = DEFAULT_DWG_TIMEOUT
    grid_directory: str | None = None
    skip_outside_grid: bool = True


@dataclass
class EntityIssue:
    severity: str
    code: str
    message: str
    layout: str
    entity_type: str
    handle: str
    source_handle: str = ""
    source_entity_type: str = ""
    source_layout: str = ""


@dataclass
class FileResult:
    input_path: str
    output_path: str | None = None
    input_entity_count: int = 0
    output_entity_count: int = 0
    transformed: Counter[str] = field(default_factory=Counter)
    approximated: Counter[str] = field(default_factory=Counter)
    local_affine: Counter[str] = field(default_factory=Counter)
    exploded: Counter[str] = field(default_factory=Counter)
    unresolved: Counter[str] = field(default_factory=Counter)
    omitted: Counter[str] = field(default_factory=Counter)
    issues: list[EntityIssue] = field(default_factory=list)
    fitted_polyline_sources: list[dict[str, Any]] = field(default_factory=list)
    hatch_boundary_sources: list[dict[str, Any]] = field(default_factory=list)
    proxy_entity_sources: list[dict[str, Any]] = field(default_factory=list)
    unresolved_entity_sources: list[dict[str, Any]] = field(default_factory=list)
    drawing_warnings: list[str] = field(default_factory=list)
    display_setup: dict[str, Any] = field(default_factory=dict)
    numerical_checks: dict[str, Any] = field(default_factory=dict)
    output_verification: dict[str, Any] = field(default_factory=dict)
    auxiliary_coordinate_repairs: list[dict[str, Any]] = field(default_factory=list)
    timings_seconds: dict[str, float] = field(default_factory=dict)
    skipped_outside_grid: Counter[str] = field(default_factory=Counter)
    outside_grid_objects: list[dict[str, Any]] = field(default_factory=list)

    def add_issue(self, severity: str, code: str, message: str, entity: Any) -> None:
        layout = entity.get_layout()
        self.issues.append(
            EntityIssue(
                severity=severity,
                code=code,
                message=message,
                layout=getattr(layout, "name", "<unknown>"),
                entity_type=entity.dxftype(),
                handle=str(getattr(entity.dxf, "handle", "") or ""),
            )
        )

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "transformed",
            "approximated",
            "local_affine",
            "exploded",
            "unresolved",
            "omitted",
            "skipped_outside_grid",
        ):
            data[key] = dict(sorted(getattr(self, key).items()))
        return data


LogCallback = Callable[[str], None]
ProgressCallback = Callable[[float, str], None]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require_dependencies() -> None:
    missing: list[str] = []
    if ezdxf is None:
        missing.append(f"ezdxf ({EZDXF_IMPORT_ERROR})")
    if CRS is None or Transformer is None or TransformerGroup is None:
        missing.append(f"pyproj ({PYPROJ_IMPORT_ERROR})")
    if missing:
        remedy = (
            "Rebuild the executable with the complete dependencies and collection "
            "options documented in README.md."
            if getattr(sys, "frozen", False)
            else "Activate the project's virtual environment and run: "
            'python -m pip install --upgrade "ezdxf==1.4.4" "pyproj==3.7.2" '
            '"Pillow>=12.0,<13". See README.md for the complete installation.'
        )
        raise ConversionError(
            "Missing Python dependencies: " + "; ".join(missing) + ". " + remedy
        )


def parse_epsg(value: str | int) -> int:
    if isinstance(value, int):
        code = value
    else:
        text = str(value).strip()
        if not text:
            raise ConversionError("An EPSG code is required.")
        head = text.split("—", 1)[0].strip()
        if head.upper().startswith("EPSG:"):
            head = head.split(":", 1)[1]
        try:
            code = int(head)
        except ValueError as exc:
            raise ConversionError(f"Invalid EPSG value: {value!r}") from exc
    if code not in EPSG_NAME_BY_CODE:
        allowed = ", ".join(str(item[0]) for item in EPSG_SYSTEMS)
        raise ConversionError(
            f"EPSG:{code} is not in the supplied CRS list. Allowed codes: {allowed}"
        )
    return code


def validate_job(job: ConversionJob) -> ConversionJob:
    require_dependencies()
    if not job.input_paths:
        raise ConversionError("Add at least one DXF or DWG input file.")
    for raw in job.input_paths:
        path = Path(raw)
        if not path.is_file():
            raise ConversionError(f"Input file does not exist: {path}")
        if path.suffix.lower() not in {".dxf", ".dwg"}:
            raise ConversionError(
                f"Unsupported input format: {path.suffix}. Use DXF or DWG."
            )
    out_dir = Path(job.output_directory)
    if not job.output_directory.strip():
        raise ConversionError("Choose an output folder.")
    parse_epsg(job.source_epsg)
    parse_epsg(job.target_epsg)
    if job.curve_tolerance is None:
        job = replace(job, curve_tolerance=default_curve_tolerance(job.source_epsg))
    if job.source_epsg == job.target_epsg:
        raise ConversionError(
            "Source and target EPSG codes are identical; no reprojection is required."
        )
    if job.output_format not in {"dxf", "dwg"}:
        raise ConversionError("Output format must be dxf or dwg.")
    if any(char in job.output_suffix for char in '/\\<>:"|?*') or any(
        ord(char) < 32 for char in job.output_suffix
    ):
        raise ConversionError(
            "The output suffix must contain filename characters only."
        )
    if not math.isfinite(job.curve_tolerance) or job.curve_tolerance <= 0:
        raise ConversionError(
            "Curve tolerance must be a finite number greater than zero."
        )
    if not math.isfinite(job.dwg_timeout_seconds) or job.dwg_timeout_seconds <= 0:
        raise ConversionError(
            "The DWG timeout must be a finite number greater than zero."
        )
    if not math.isfinite(job.reprojection_tolerance_m) or job.reprojection_tolerance_m <= 0:
        raise ConversionError("Reprojection tolerance must be a finite, positive number of metres.")
    CRS.from_epsg(job.source_epsg)
    CRS.from_epsg(job.target_epsg)
    planned: dict[str, Path] = {}
    inputs = {os.path.normcase(str(Path(raw).resolve())) for raw in job.input_paths}
    for raw in job.input_paths:
        source = Path(raw)
        target = out_dir / f"{source.stem}{job.output_suffix}.{job.output_format}"
        key = os.path.normcase(str(target.resolve()))
        if key in inputs or (
            target.exists()
            and any(target.samefile(Path(raw_input)) for raw_input in job.input_paths)
        ):
            raise ConversionError(
                f"An output would overwrite an input drawing: {target}"
            )
        if target.exists() and not job.overwrite:
            raise ConversionError(
                f"Output already exists and overwrite is disabled: {target}"
            )
        if target.exists() and not target.is_file():
            raise ConversionError(f"The output path is not a regular file: {target}")
        if key in planned:
            raise ConversionError(
                "Two input drawings would create the same output file: "
                f"{planned[key]} and {source} -> {target.name}. Convert them separately or rename one input."
            )
        planned[key] = source
    out_dir.mkdir(parents=True, exist_ok=True)
    return job


def _find_executable(candidate: str | None) -> str | None:
    if not candidate:
        return None
    expanded = Path(os.path.expandvars(os.path.expanduser(candidate)))
    if expanded.is_file():
        return str(expanded.resolve())
    located = shutil.which(candidate)
    return str(Path(located).resolve()) if located else None


def detect_oda_converter(preferred: str | None = None) -> str | None:
    candidates = [
        preferred,
        os.environ.get("ODA_FILE_CONVERTER"),
        os.environ.get("ODA_CONVERTER"),
        "ODAFileConverter.exe",
        "ODAFileConverter",
    ]
    for candidate in candidates:
        found = _find_executable(candidate)
        if found:
            return found
    if os.name == "nt":
        roots = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
        ]
        patterns = (
            "ODA/ODAFileConverter*/ODAFileConverter.exe",
            "ODAFileConverter*/ODAFileConverter.exe",
            "Open Design Alliance/**/ODAFileConverter.exe",
        )
        for root in roots:
            for pattern in patterns:
                with contextlib.suppress(OSError):
                    match = next(root.glob(pattern), None)
                    if match and match.is_file():
                        return str(match.resolve())
    return None


_EXTERNAL_PROCESS_LOCK = threading.Lock()


@contextlib.contextmanager
def _external_process_environment() -> Iterator[dict[str, str] | None]:
    """Keep bundled Python libraries out of external programs such as ODA."""
    if not getattr(sys, "frozen", False):
        yield None
        return

    environment = os.environ.copy()
    bundle_directory = getattr(sys, "_MEIPASS", None)
    if sys.platform not in {"win32", "darwin"}:
        library_variable = (
            "LIBPATH" if sys.platform.startswith("aix") else "LD_LIBRARY_PATH"
        )
        original = environment.get(f"{library_variable}_ORIG")
        if original is None:
            environment.pop(library_variable, None)
        else:
            environment[library_variable] = original

    if bundle_directory:
        bundle_path = os.path.normcase(os.path.abspath(bundle_directory))

        def outside_bundle(entry: str) -> bool:
            if not entry:
                return True
            candidate = os.path.normcase(os.path.abspath(entry.strip('"')))
            try:
                return os.path.commonpath((bundle_path, candidate)) != bundle_path
            except ValueError:
                return True  # Paths on different Windows drives cannot overlap.

        for variable in ("PATH", "DYLD_LIBRARY_PATH"):
            if variable in environment:
                environment[variable] = os.pathsep.join(
                    entry
                    for entry in environment[variable].split(os.pathsep)
                    if outside_bundle(entry)
                )

    if sys.platform != "win32":
        yield environment
        return

    # SetDllDirectory is process-wide: concurrent preview and conversion workers
    # must serialize the brief interval surrounding child-process creation.
    with _EXTERNAL_PROCESS_LOCK:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_directory = kernel32.GetDllDirectoryW
        get_directory.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p)
        get_directory.restype = ctypes.c_uint32
        set_directory = kernel32.SetDllDirectoryW
        set_directory.argtypes = (ctypes.c_wchar_p,)
        set_directory.restype = ctypes.c_int
        ctypes.set_last_error(0)
        required = get_directory(0, None)
        if not required and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(required + 1)
        if required:
            copied = get_directory(len(buffer), buffer)
            if not copied or copied >= len(buffer):
                raise OSError("Could not read the process DLL search directory.")
        original_directory = buffer.value or None
        if not set_directory(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield environment
        finally:
            if not set_directory(original_directory):
                raise ctypes.WinError(ctypes.get_last_error())


def _start_external_process(
    command: Sequence[str], **options: Any
) -> subprocess.Popen[Any]:
    """Create a child while temporarily restoring the system library search path."""
    process = None
    try:
        with _external_process_environment() as environment:
            process = subprocess.Popen(list(command), env=environment, **options)
    except BaseException:
        # A failed DLL-directory restoration must not leave a launched child behind.
        if process is not None:
            with contextlib.suppress(OSError):
                process.kill()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                process.communicate(timeout=5)
        raise
    return process


def _run_process(
    command: Sequence[str], timeout_seconds: int, cancel: CancellationToken
) -> str:
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        process = _start_external_process(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            startupinfo=startupinfo,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except OSError as exc:
        raise ConversionError(f"Could not start ODA File Converter: {exc}") from exc

    deadline = time.monotonic() + max(1, int(timeout_seconds))
    output = ""

    def stop(force: bool) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            command = ["taskkill", "/PID", str(process.pid), "/T"]
            if force:
                command.append("/F")
            with contextlib.suppress(Exception):
                killer = _start_external_process(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    killer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    killer.kill()
                    killer.wait(timeout=5)
        else:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)

    try:
        while True:
            if cancel.cancelled:
                stop(False)
                raise CancelledError("DWG conversion cancelled by the user.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stop(True)
                raise ConversionError(
                    f"ODA File Converter timed out after {timeout_seconds} seconds.\n{output[-4000:]}"
                )
            try:
                output, _ = process.communicate(timeout=min(0.25, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            stop(True)
            with contextlib.suppress(Exception):
                process.communicate(timeout=5)
    if process.returncode != 0:
        raise ConversionError(
            f"ODA File Converter failed with exit code {process.returncode}.\n{output[-8000:]}"
        )
    return output


def _oda_convert(
    source: Path,
    target_extension: str,
    oda_executable: str,
    timeout_seconds: int,
    cancel: CancellationToken,
) -> Path:
    """Convert one isolated file with ODA and return a temporary result path."""
    target_extension = target_extension.lower().lstrip(".")
    if target_extension not in {"dxf", "dwg"}:
        raise ConversionError(f"ODA target format is not supported: {target_extension}")
    root = Path(tempfile.mkdtemp(prefix="cad_epsg_oda_"))
    try:
        input_dir = root / "input"
        output_dir = root / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        isolated = input_dir / source.name
        shutil.copy2(source, isolated)
        command = [
            oda_executable,
            str(input_dir),
            str(output_dir),
            "ACAD2018",
            target_extension.upper(),
            "0",
            "1",
            isolated.name,
        ]
        converter_output = _run_process(command, timeout_seconds, cancel)
        matches = [
            path
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() == f".{target_extension}"
            and path.stem.casefold() == source.stem.casefold()
        ]
        if len(matches) != 1:
            shutil.rmtree(root, ignore_errors=True)
            raise ConversionError(
                "ODA File Converter did not create exactly one expected output file. "
                f"Found {len(matches)}.\n{converter_output[-4000:]}"
            )
        return matches[0]
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


@contextlib.contextmanager
def prepared_dxf_input(
    source: Path,
    job: ConversionJob,
    cancel: CancellationToken,
    log: LogCallback,
) -> Iterator[Path]:
    if source.suffix.lower() == ".dxf":
        yield source
        return
    oda = detect_oda_converter(job.oda_executable)
    if not oda:
        raise ConversionError(
            "DWG input requires ODA File Converter. Install it or choose its executable "
            "in Advanced options. DXF input does not require ODA."
        )
    log(f"Converting DWG input to an audited temporary DXF with ODA: {source.name}")
    temp_path = _oda_convert(source, "dxf", oda, job.dwg_timeout_seconds, cancel)
    temp_root = temp_path.parents[1]
    try:
        yield temp_path
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def load_dxf(
    path: Path, recover: bool, log: LogCallback
) -> tuple[Any, dict[str, int | bool]]:
    recovered = False
    auditor = None
    try:
        document = ezdxf.readfile(str(path))
    except Exception as first_exc:
        if not recover:
            raise ConversionError(f"Could not read DXF: {first_exc}") from first_exc
        log(f"Normal DXF read failed; trying ezdxf recovery: {first_exc}")
        try:
            document, auditor = ezdxf_recover.readfile(str(path))
            recovered = True
        except Exception as second_exc:
            raise ConversionError(
                f"Could not read or recover DXF: {second_exc}"
            ) from second_exc
    if recover and auditor is None:
        with contextlib.suppress(Exception):
            auditor = document.audit()
    return document, {
        "recovered": recovered,
        "audit_errors": len(getattr(auditor, "errors", []) or []) if auditor else 0,
        "audit_fixes": len(getattr(auditor, "fixes", []) or []) if auditor else 0,
    }


def _graphic_attributes(entity: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for name in (
        "layer",
        "linetype",
        "color",
        "lineweight",
        "ltscale",
        "invisible",
        "true_color",
        "color_name",
        "transparency",
        "material_handle",
        "plotstyle_enum",
        "plotstyle_handle",
    ):
        if entity.dxf.hasattr(name):
            attributes[name] = entity.dxf.get(name)
    return attributes


def _copy_xdata(source: Any, target: Any) -> None:
    document = source.doc
    if document is None:
        return
    for appid in document.appids:
        name = appid.dxf.name
        with contextlib.suppress(Exception):
            data = source.get_xdata(name)
            if data:
                target.set_xdata(name, list(data))
    with contextlib.suppress(Exception):
        if "CAD_EPSG" not in document.appids:
            document.appids.add("CAD_EPSG")
        target.set_xdata(
            "CAD_EPSG",
            [
                (1000, f"SOURCE_TYPE={source.dxftype()}"),
                (1000, f"SOURCE_HANDLE={getattr(source.dxf, 'handle', '')}"),
            ],
        )


def _point_tuple(value: Any) -> tuple[float, float, float]:
    vector = Vec3(value)
    return float(vector.x), float(vector.y), float(vector.z)


# Greenwich geographic CRS, local NTv2 file and expected source datum header.
# Accept the DGT IGP2011 grids and the datum-specific FCUP JAG08_01 grids.
# These are horizontal corrections, not ellipsoidal-height/geoid models.
GRID_FAMILIES = {
    "datum73": (4274, "pt73_e89.gsb", "DATUM73"),
    "ed50": (4230, "ptED_e89.gsb", "ED50_PT"),
    "lisbon_bessel": (4666, "ptLB_e89.gsb", "DATUMLXB"),
    "lisbon": (4207, "ptLX_e89.gsb", "DATUMLX"),
}
GRID_FAMILY_BY_EPSG = {
    27493: "datum73",
    4274: "datum73",
    4230: "ed50",
    23029: "ed50",
    4666: "lisbon_bessel",
    2963: "lisbon_bessel",
    5017: "lisbon_bessel",
    4207: "lisbon",
    5018: "lisbon",
    20790: "lisbon",
    20791: "lisbon",
}


# Within each resource directory, prefer the configured canonical grid aliases.
# The directory priority is retained: an explicit folder remains exclusive.
GRID_FILENAMES = {
    "pt73_e89.gsb": ("pt73_e89.gsb", "D73_ETRS89_geo.gsb"),
    "ptLX_e89.gsb": ("ptLX_e89.gsb", "DLX_ETRS89_geo.gsb"),
    "ptED_e89.gsb": ("ptED_e89.gsb",),
    "ptLB_e89.gsb": ("ptLB_e89.gsb",),
}


def default_curve_tolerance(source_epsg: int) -> float:
    """Source-coordinate sagitta; identical defaults for the GUI, CLI and API."""
    return (DEFAULT_ANGULAR_CURVE_TOLERANCE
            if CRS.from_epsg(source_epsg).is_geographic
            else DEFAULT_CURVE_TOLERANCE)


def _supported_bonne(crs: Any) -> Any:
    """Represent the two south-oriented Bonne CRSs without changing axes/meridian.

    PROJ 9.5.1 lacks EPSG method 9828. For these zero-offset CRS definitions,
    ordinary Bonne (9827) plus the original south/west axis mapping is equivalent.
    The Greenwich-based EPSG:5017 must receive the same handling as EPSG:2963.
    """
    if crs.to_epsg() not in SOUTH_WEST_EPSG_CODES:
        return crs
    definition = crs.to_json_dict()
    definition["conversion"]["method"] = {
        "name": "Bonne", "id": {"authority": "EPSG", "code": 9827}
    }
    definition.pop("id", None)
    return CRS.from_json_dict(definition)


def _crs_interface(crs: Any) -> dict[str, Any]:
    """Describe the CAD interface, which is not always native EPSG axis order."""
    if crs.is_geographic:
        axes, units = ["longitude", "latitude", "Z"], ["degree", "degree", "metre"]
    elif crs.is_geocentric:
        axes, units = ["geocentric X", "geocentric Y", "geocentric Z"], ["metre"] * 3
    elif crs.to_epsg() in SOUTH_WEST_EPSG_CODES:
        axes, units = ["southing", "westing", "Z"], ["metre"] * 3
    else:
        axes, units = ["easting", "northing", "Z"], ["metre"] * 3
    return {"crs": crs.to_string(), "cad_axes": axes, "units": units,
            "native_axes": [{"name": a.name, "direction": a.direction, "unit": a.unit_name}
                            for a in crs.axis_info]}


def _default_area(source: Any, target: Any) -> tuple[float, float, float, float] | None:
    """Use common declared coverage when no drawing-specific area was supplied."""
    if source.area_of_use is None or target.area_of_use is None:
        return None
    a, b = source.area_of_use.bounds, target.area_of_use.bounds
    if a[0] > a[2] or b[0] > b[2]:
        return None  # Wrapped areas need explicit point-dependent selection.
    bounds = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return bounds if bounds[0] < bounds[2] and bounds[1] < bounds[3] else None


def grid_search_directories(grid_directory: str | None = None) -> list[Path]:
    """Resolve external resources beside the .py or frozen executable, not cwd."""
    if grid_directory:
        return [Path(grid_directory).expanduser().resolve()]
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    roots.append(Path(__file__).resolve().parent)
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS).resolve())
    return list(dict.fromkeys(roots))


def discover_grid_paths(grid_directory: str | None = None) -> dict[str, Path]:
    """Find datum-specific names case-insensitively, with deterministic priority."""
    found: dict[str, Path] = {}
    for root in grid_search_directories(grid_directory):
        if not root.is_dir():
            continue
        try:
            entries: dict[str, Path] = {}
            for item in sorted(root.iterdir(), key=lambda item: item.name):
                if item.is_file() and item.suffix.casefold() == ".gsb":
                    key = item.name.casefold()
                    if key in entries:
                        raise CoordinateTransformationError(
                            f"Ambiguous grid filenames differing only in case: {entries[key]} and {item}."
                        )
                    entries[key] = item
        except OSError as exc:
            raise CoordinateTransformationError(f"Cannot inspect NTv2 folder {root}: {exc}") from exc
        for canonical, alternatives in GRID_FILENAMES.items():
            if canonical not in found:
                for filename in alternatives:
                    if filename.casefold() in entries:
                        found[canonical] = entries[filename.casefold()].resolve()
                        break
    return found


def _read_grid_metadata(path: Path, expected_datum: str) -> dict[str, Any]:
    """Validate the complete NTv2 structure, datum, ellipsoids and every node."""
    try:
        data = path.read_bytes()
        if len(data) < 352 or data[:8] != b"NUM_OREC":
            raise ValueError("not an NTv2 binary grid")
        endian = "<" if struct.unpack_from("<i", data, 8)[0] == 11 else ">"

        def records(offset: int) -> dict[str, bytes]:
            if offset + 176 > len(data):
                raise ValueError("truncated NTv2 header")
            return {data[i:i + 8].decode("ascii").strip(): data[i + 8:i + 16]
                    for i in range(offset, offset + 176, 16)}

        overview = records(0)
        def integer(raw: bytes) -> int:
            return struct.unpack_from(endian + "i", raw)[0]

        def number(raw: bytes) -> float:
            return struct.unpack(endian + "d", raw)[0]
        if integer(overview["NUM_OREC"]) != 11 or integer(overview["NUM_SREC"]) != 11:
            raise ValueError("unsupported NTv2 overview/subgrid header length")
        count = integer(overview["NUM_FILE"])
        if count < 1 or count > (len(data) - 176) // 176:
            raise ValueError("invalid NTv2 subgrid count")
        source = overview["SYSTEM_F"].decode("ascii").strip()
        target = overview["SYSTEM_T"].decode("ascii").strip()
        units = overview["GS_TYPE"].decode("ascii").strip()
        if (source, target, units) != (expected_datum, "ETRS89", "SECONDS"):
            raise ValueError(
                f"unexpected datum/units: {source} -> {target}, {units}; "
                f"expected {expected_datum} -> ETRS89, SECONDS"
            )
        source_code = next(v[0] for v in GRID_FAMILIES.values() if v[2] == expected_datum)
        ellipsoids = {}
        for suffix, code in (("F", source_code), ("T", 4258)):
            ellipsoid = CRS.from_epsg(code).ellipsoid
            a, b = number(overview[f"MAJOR_{suffix}"]), number(overview[f"MINOR_{suffix}"])
            # DGT's binary overview rounds the minor axes to millimetres.
            if not (math.isfinite(a) and math.isfinite(b)
                    and abs(a - ellipsoid.semi_major_metre) <= 0.002
                    and abs(b - ellipsoid.semi_minor_metre) <= 0.002):
                raise ValueError(f"incompatible {suffix} ellipsoid axes: {a}, {b}")
            ellipsoids[suffix] = {"semi_major_m": a, "semi_minor_m": b}
        subgrids: list[dict[str, Any]] = []
        names: set[str] = set()
        offset = 176
        for _ in range(count):
            header = records(offset)
            name = header["SUB_NAME"].decode("ascii").strip()
            parent = header["PARENT"].decode("ascii").strip()
            if not name or name in names:
                raise ValueError("empty or duplicate NTv2 subgrid name")
            names.add(name)
            south, north, east, west, dy, dx = (
                number(header[k]) for k in ("S_LAT", "N_LAT", "E_LONG", "W_LONG", "LAT_INC", "LONG_INC")
            )
            if not all(math.isfinite(v) for v in (south, north, east, west, dy, dx)):
                raise ValueError("non-finite subgrid extent or spacing")
            if not (-324000 <= south < north <= 324000 and east < west
                    and -648000 <= east <= 648000 and -648000 <= west <= 648000
                    and dx > 0 and dy > 0):
                raise ValueError("invalid subgrid extent or spacing")
            row_steps, column_steps = (north - south) / dy, (west - east) / dx
            rows, columns = round(row_steps) + 1, round(column_steps) + 1
            nodes = integer(header["GS_COUNT"])
            if (abs(row_steps - (rows - 1)) > 1e-6 or abs(column_steps - (columns - 1)) > 1e-6
                    or nodes != rows * columns):
                raise ValueError("subgrid node count does not match its extent and spacing")
            data_start, data_end = offset + 176, offset + 176 + nodes * 16
            if data_end > len(data):
                raise ValueError("truncated NTv2 node data")
            for node in struct.iter_unpack(endian + "4f", memoryview(data)[data_start:data_end]):
                if not all(math.isfinite(v) for v in node):
                    raise ValueError("non-finite shift/accuracy value in NTv2 node data")
            subgrids.append({
                "name": name, "parent": parent, "node_count": nodes,
                "rows": rows, "columns": columns,
                "spacing_arcseconds": [dx, dy],
                "bounds_degrees": {"west": -west / 3600, "east": -east / 3600,
                                   "south": south / 3600, "north": north / 3600},
            })
            offset = data_end
        if offset != len(data) and not (len(data) - offset == 16 and data[offset:offset + 8].strip() == b"END"):
            raise ValueError("unexpected bytes after the final NTv2 subgrid")
        by_name = {sub["name"]: sub for sub in subgrids}
        for sub in subgrids:
            seen = {sub["name"]}
            current = sub
            while current["parent"].upper() != "NONE":
                if current["parent"] not in by_name or current["parent"] in seen:
                    raise ValueError("missing or cyclic NTv2 subgrid parent")
                parent = by_name[current["parent"]]
                c, b = current["bounds_degrees"], parent["bounds_degrees"]
                if not (b["west"] <= c["west"] <= c["east"] <= b["east"]
                        and b["south"] <= c["south"] <= c["north"] <= b["north"]):
                    raise ValueError("child subgrid lies outside its parent")
                seen.add(parent["name"])
                current = parent
        version = overview["VERSION"].decode("ascii").strip()
        return {
            "filename": path.name, "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
            "version": version, "source_datum": source, "target_datum": target,
            "horizontal_only": True, "ellipsoids": ellipsoids,
            "subgrid_count": count, "subgrids": subgrids,
            "first_subgrid_bounds_degrees": subgrids[0]["bounds_degrees"],
            "structure_and_nodes_validated": True,
            "accuracy_scope": "Grid-model statistics are not a per-point accuracy guarantee.",
        }
    except (OSError, UnicodeError, ValueError, KeyError, StopIteration, struct.error) as exc:
        raise CoordinateTransformationError(f"Invalid local grid {path}: {exc}") from exc


@dataclass
class CoordinateOperation:
    """Explicit scalar chain: source units -> geographic/grid stages -> target units."""

    stages: list[tuple[str, Any]] = field(default_factory=list)
    grids: list[dict[str, Any]] = field(default_factory=list)
    best_available: bool = True
    accuracy: float = 0.0
    source_crs: Any = None
    target_crs: Any = None
    stage_details: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    area_of_interest: tuple[float, float, float, float] | None = None
    inverse_grid_boundary_recoveries: int = 0

    @property
    def description(self) -> str:
        return " -> ".join(label for label, _ in self.stages) or "Identity (same CRS)"

    @property
    def definition(self) -> str:
        return "\n".join(str(stage.definition) for _, stage in self.stages)

    @staticmethod
    def _check_coordinates(values: tuple[float, ...], crs: Any) -> None:
        if not all(math.isfinite(v) for v in values):
            raise CoordinateTransformationError("Coordinates must all be finite numbers.")
        if crs is not None and crs.is_geographic:
            if not (-180 <= values[0] <= 180 and -90 <= values[1] <= 90):
                raise CoordinateTransformationError(
                    "Geographic CAD coordinates must be X=longitude [-180, 180] and "
                    "Y=latitude [-90, 90], in decimal degrees; check the source EPSG/axis order."
                )
        if crs is not None and crs.is_geocentric:
            if len(values) != 3 or sum(v * v for v in values) < 1:
                raise CoordinateTransformationError("Geocentric conversion requires valid Earth-centred XYZ in metres.")

    @staticmethod
    def _check_grid_location(point: tuple[float, ...], bounds: Any) -> None:
        if not bounds:
            return
        # Geographic DEGREES at this boundary, never projected XY or NTv2 arcseconds.
        # This slack only accommodates floating-point evaluation; no coordinates move.
        if any(b["west"] - 1e-12 <= point[0] <= b["east"] + 1e-12
               and b["south"] - 1e-12 <= point[1] <= b["north"] + 1e-12 for b in bounds):
            return
        limits = "; ".join(
            f"longitude [{b['west']:.12g}, {b['east']:.12g}], "
            f"latitude [{b['south']:.12g}, {b['north']:.12g}]" for b in bounds[:4])
        raise GridCoverageError(
            f"The location is outside the actual NTv2 source coverage: "
            f"longitude={point[0]:.12f}, latitude={point[1]:.12f} degrees. "
            f"Valid source-datum grid bounds: {limits}. Grid-edge extrapolation is disabled.",
            details={"grid_source_longitude": float(point[0]),
                     "grid_source_latitude": float(point[1]), "bounds_degrees": bounds},
        )

    def _inverse_grid_at_boundary(self, point: tuple[float, ...], index: int) -> tuple[float, ...]:
        """Invert the SAME grid when PROJ cannot seed its inverse at a shifted edge.

        Only numerical trial seeds are constrained to a source rectangle. Every
        forward evaluation lies inside real source coverage. A result is accepted
        only if its forward image matches the untouched target point within 1e-12
        degrees. This does not clamp geometry, extrapolate shifts, or select a
        different datum model. No source solution raises a typed grid-coverage error.
        """
        detail = self.stage_details[index]
        bounds = detail.get("source_coverage_degrees") or []
        transformer = self.stages[index][1]
        forward_direction = "INVERSE" if detail.get("direction") == "inverse" else "FORWARD"
        target = tuple(float(v) for v in point)
        tolerance = 1e-12
        for b in bounds:
            x = min(b["east"], max(b["west"], target[0]))
            y = min(b["north"], max(b["south"], target[1]))
            for _ in range(16):
                trial = (x, y, *target[2:])
                self._check_grid_location(trial, bounds)
                try:
                    mapped = transformer.transform(*trial, errcheck=True, direction=forward_direction)
                except Exception:
                    break
                if not all(math.isfinite(v) for v in mapped):
                    break
                dx, dy = target[0] - mapped[0], target[1] - mapped[1]
                if max(abs(dx), abs(dy)) <= tolerance:
                    self.inverse_grid_boundary_recoveries += 1
                    return trial
                nx = min(b["east"], max(b["west"], x + dx))
                ny = min(b["north"], max(b["south"], y + dy))
                if nx == x and ny == y:
                    break
                x, y = nx, ny
        raise GridCoverageError(
            f"No inverse source location inside the actual NTv2 coverage reproduces "
            f"target longitude={target[0]:.12f}, latitude={target[1]:.12f}. "
            "No extrapolation or coordinate clamping was accepted.")

    def transform(
        self, x: float, y: float, z: float | None = None,
        errcheck: bool = True, *, direction: str = "FORWARD",
    ) -> tuple[float, ...]:
        """Never disable validation; errcheck is retained for Transformer-compatible calls."""
        if direction not in {"FORWARD", "INVERSE"}:
            raise ValueError("direction must be FORWARD or INVERSE")
        values = (float(x), float(y)) if z is None else (float(x), float(y), float(z))
        inverse = direction == "INVERSE"
        self._check_coordinates(values, self.target_crs if inverse else self.source_crs)
        indexes = range(len(self.stages) - 1, -1, -1) if inverse else range(len(self.stages))
        for index in indexes:
            label, transformer = self.stages[index]
            detail = self.stage_details[index] if index < len(self.stage_details) else {}
            bounds = detail.get("source_coverage_degrees")
            grid_forward = (detail.get("direction") == "forward") != inverse


            try:
                if grid_forward:
                    self._check_grid_location(values, bounds)
                try:
                    values = transformer.transform(*values, errcheck=True, direction=direction)
                except Exception as exc:
                    # Retry only a grid-domain failure, not a missing resource or
                    # unrelated PROJ error. The original datum pipeline is retained.
                    if bounds and not grid_forward and "outside grid" in str(exc).lower():
                        values = self._inverse_grid_at_boundary(values, index)
                    else:
                        raise
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("non-finite output coordinate")
                if not grid_forward:
                    self._check_grid_location(values, bounds)
            except Exception as exc:
                error_type = GridCoverageError if isinstance(exc, GridCoverageError) else CoordinateTransformationError
                detail_args = ({"details": {**exc.details, "stage": label,
                                "input_coordinates": [float(x), float(y)] + ([] if z is None else [float(z)]),
                                "direction": direction}} if isinstance(exc, GridCoverageError) else {})
                raise error_type(
                    f"Coordinate transformation failed at {label}: {exc}. "
                    "Check the source EPSG, units and grid coverage. Required NTv2 "
                    "stages have no optional-grid or null-shift fallback.", **detail_args
                ) from exc
        values = tuple(float(v) for v in values)
        self._check_coordinates(values, self.source_crs if inverse else self.target_crs)
        return values

    def transform_many(self, coordinates: Any, *, direction: str = "FORWARD") -> Any:
        """float64 array path with exactly the scalar chain's finite/domain/grid checks.

        On failure, replay only for diagnostics; never return partial/invalid results.
        Callers use bounded chunks so cancellation and progress remain responsive.
        """
        if direction not in {"FORWARD", "INVERSE"}:
            raise ValueError("direction must be FORWARD or INVERSE")
        original = np.asarray(coordinates, dtype=np.float64)
        if original.ndim != 2 or original.shape[1] not in (2, 3):
            raise ValueError("Coordinate array must have shape (N, 2) or (N, 3).")
        if not len(original):
            return original.copy()
        values = original.copy()
        inverse = direction == "INVERSE"

        def validate(array: Any, crs: Any) -> None:
            if not np.isfinite(array).all():
                raise CoordinateTransformationError("Coordinates must all be finite numbers.")
            if crs is not None and crs.is_geographic:
                if np.any(np.abs(array[:, 0]) > 180) or np.any(np.abs(array[:, 1]) > 90):
                    raise CoordinateTransformationError("Geographic coordinates are outside the longitude/latitude range.")
            if crs is not None and crs.is_geocentric:
                if array.shape[1] != 3 or np.any(np.sum(array * array, axis=1) < 1):
                    raise CoordinateTransformationError("Invalid Earth-centred XYZ coordinates.")

        def coverage(array: Any, bounds: Any) -> None:
            if not bounds:
                return
            valid = np.zeros(len(array), dtype=bool)
            x, y = array[:, 0], array[:, 1]
            for b in bounds:
                valid |= ((x >= b["west"] - 1e-12) & (x <= b["east"] + 1e-12)
                          & (y >= b["south"] - 1e-12) & (y <= b["north"] + 1e-12))
            if not valid.all():
                self._check_grid_location(tuple(array[np.flatnonzero(~valid)[0]]), bounds)

        try:
            validate(values, self.target_crs if inverse else self.source_crs)
            indexes = range(len(self.stages)-1, -1, -1) if inverse else range(len(self.stages))
            for index in indexes:
                _, transformer = self.stages[index]
                detail = self.stage_details[index] if index < len(self.stage_details) else {}
                bounds = detail.get("source_coverage_degrees")
                grid_forward = (detail.get("direction") == "forward") != inverse
                if grid_forward:
                    coverage(values, bounds)
                columns = transformer.transform(*(values[:, i] for i in range(values.shape[1])),
                                                errcheck=True, direction=direction)
                values = np.column_stack(columns)
                if not np.isfinite(values).all():
                    raise CoordinateTransformationError("Non-finite array transformation result.")
                if not grid_forward:
                    coverage(values, bounds)
            validate(values, self.source_crs if inverse else self.target_crs)
        except Exception:
            # A PROJ array may fail on an inverse edge that the safeguarded scalar
            # inverse resolves. Accept only if EVERY checked scalar point succeeds.
            restored = []
            for index, point in enumerate(original):
                try:
                    restored.append(self.transform(*point, direction=direction))
                except CoordinateTransformationError as exc:
                    exc.add_note(f"Coordinate batch index: {index}.")
                    raise
            return np.asarray(restored, dtype=np.float64)
        return values

    def report(self) -> dict[str, Any]:
        return {
            "method": "Local NTv2 grid chain" if self.grids else "PROJ coordinate operation",
            "description": self.description, "definition": self.definition,
            "grids": self.grids, "stages": self.stage_details,
            "source_interface": _crs_interface(self.source_crs) if self.source_crs else None,
            "target_interface": _crs_interface(self.target_crs) if self.target_crs else None,
            "area_of_interest_degrees": self.area_of_interest,
            "best_operation_available": self.best_available,
            "accuracy_metres": None if self.accuracy < 0 else self.accuracy,
            "warnings": self.warnings, "network_enabled": False,
            "inverse_grid_boundary_recoveries": self.inverse_grid_boundary_recoveries,
            "inverse_grid_boundary_policy": "Same-grid bounded numerical inversion; forward residual <= 1e-12 degree; no extrapolation or datum substitution.",
            "accuracy_note": (
                "Stage accuracies are PROJ metadata, not numerical rounding tolerances. "
                "The sum of stated stage accuracies is not an independently verified error bound. "
                "Overall accuracy is unknown if any stage lacks accuracy metadata. "
                "NTv2 is horizontal-only. No geoid model or coordinate-epoch correction is applied."
            ),
        }


def build_coordinate_operation(
    source_epsg: int,
    target_epsg: int,
    allow_ballpark: bool = False,
    grid_directory: str | None = None,
    *,
    allow_degraded: bool = False,
    area_of_interest: tuple[float, float, float, float] | None = None,
) -> CoordinateOperation:
    """Build mandatory datum-specific grids and the best locally installed PROJ stages.

    Grid shifts operate on Greenwich geographic coordinates, never on projected
    metres. Projection-only transformations within one datum do not use a grid.
    No online grid download or lower-accuracy substitution is performed implicitly.
    """
    require_dependencies()
    network.set_network_enabled(False)
    source_epsg, target_epsg = parse_epsg(source_epsg), parse_epsg(target_epsg)
    source, target = CRS.from_epsg(source_epsg), CRS.from_epsg(target_epsg)
    source_family = GRID_FAMILY_BY_EPSG.get(source_epsg)
    target_family = GRID_FAMILY_BY_EPSG.get(target_epsg)
    geocentric = source.is_geocentric or target.is_geocentric
    if geocentric and (source_family or target_family) and source_family != target_family:
        raise CoordinateTransformationError(
            "This historical-datum/geocentric pair needs an ellipsoidal-height datum "
            "transformation that the horizontal NTv2 grids do not supply. Convert "
            "horizontal coordinates separately and establish compatible ellipsoidal "
            "heights before generating geocentric XYZ. Unchanged historical heights "
            "will not be silently treated as target-datum ellipsoidal heights."
        )
    area = area_of_interest or _default_area(source, target)
    operation = CoordinateOperation(source_crs=source, target_crs=target, area_of_interest=area)
    paths = discover_grid_paths(grid_directory)

    def add_projection(a: Any, b: Any) -> None:
        a, b = CRS.from_user_input(a), CRS.from_user_input(b)
        a, b = _supported_bonne(a), _supported_bonne(b)
        if geocentric:
            # PROJ needs explicit 3D CRSs to use height consistently, including
            # when the other interface is a projected CRS with a CAD Z value.
            a, b = a.to_3d(), b.to_3d()
        if a.equals(b):
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            group = TransformerGroup(
                a, b, always_xy=True, allow_ballpark=allow_ballpark,
                area_of_interest=AreaOfInterest(*area) if area else None,
            )
        missing = sorted({grid.short_name for item in group.unavailable_operations
                          for grid in item.grids if not grid.available})
        if not group.transformers:
            raise CoordinateTransformationError(
                f"No installed coordinate operation is available from {a.name} to {b.name}. "
                + ("Missing grids: " + ", ".join(missing) + "." if missing else "")
            )
        if not group.best_available and not allow_degraded:
            raise CoordinateTransformationError(
                "The best known PROJ operation is unavailable; lower-accuracy substitution "
                "is disabled. Install the required PROJ resources"
                + (": " + ", ".join(missing) if missing else "")
                + ". The separate 'Allow lower-accuracy installed operations' setting "
                "can explicitly permit a degraded non-mandatory stage."
            )
        transformer = group.transformers[0]
        ballpark = any(item.has_ballpark_transformation for item in transformer.operations)
        details = {
            "kind": "PROJ", "description": transformer.description,
            "definition": transformer.definition,
            "source_crs": a.to_string(), "target_crs": b.to_string(),
            "accuracy_metres": transformer.accuracy if transformer.accuracy >= 0 else None,
            "best_available": group.best_available, "ballpark": ballpark,
            "missing_alternative_grids": missing,
            "area_of_use_degrees": list(transformer.area_of_use.bounds) if transformer.area_of_use else None,
            "grids": [{"filename": g.short_name, "available": g.available, "path": g.full_name}
                      for item in transformer.operations for g in item.grids],
        }
        operation.stage_details.append(details)
        operation.stages.append((transformer.description, transformer))
        operation.best_available &= group.best_available
        if not group.best_available:
            operation.warnings.append("Explicit lower-accuracy override used: " + transformer.description)
        if ballpark:
            operation.warnings.append("Explicit ballpark operation used: " + transformer.description)
        if operation.accuracy >= 0:
            operation.accuracy = -1.0 if transformer.accuracy < 0 else operation.accuracy + transformer.accuracy

    def add_grid(family: str, inverse: bool = False) -> None:
        _, filename, expected = GRID_FAMILIES[family]
        path = paths.get(filename)
        if path is None:
            names = " or ".join(GRID_FILENAMES[filename])
            searched = "; ".join(str(root) for root in grid_search_directories(grid_directory))
            raise CoordinateTransformationError(
                f"Required NTv2 grid is missing: {names}. Put the correct datum-specific "
                f"file beside the script/executable or select its folder. Searched: {searched}"
            )
        metadata = _read_grid_metadata(path, expected)
        absolute = path.as_posix()
        if any(char in absolute for char in ('"', ",", "\n", "\r")):
            raise CoordinateTransformationError("Select an NTv2 folder without commas, quotes or line breaks.")
        pipeline = (
            "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
            f'+step {"+inv " if inverse else ""}+proj=hgridshift +grids="{absolute}" '
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        )
        try:
            transformer = Transformer.from_pipeline(pipeline)
        except Exception as exc:
            raise CoordinateTransformationError(f"Cannot load required NTv2 grid {path}: {exc}") from exc
        metadata["direction"] = "inverse" if inverse else "forward"
        metadata["canonical_alias"] = filename
        operation.grids.append(metadata)
        label = f"NTv2 {path.name} ({metadata['direction']})"
        operation.stages.append((label, transformer))
        operation.stage_details.append({
            "kind": "NTv2", "description": label, "definition": transformer.definition,
            "accuracy_metres": None, "horizontal_only": True,
            "grid_sha256": metadata["sha256"], "grid_path": str(path),
            "direction": metadata["direction"],
            "source_coverage_degrees": [sub["bounds_degrees"] for sub in metadata["subgrids"]],
        })
        operation.accuracy = -1.0

    if source_family is not None and source_family == target_family:
        geographic = GRID_FAMILIES[source_family][0]
        add_projection(source, geographic)
        add_projection(geographic, target)
    elif source_family is not None or target_family is not None:
        if source_family:
            add_projection(source, GRID_FAMILIES[source_family][0])
            add_grid(source_family)
        else:
            add_projection(source, 4258)
        if target_family:
            add_grid(target_family, inverse=True)
            add_projection(GRID_FAMILIES[target_family][0], target)
        else:
            add_projection(4258, target)
    else:
        add_projection(source, target)
    if (source_epsg in WGS84_EPSG_CODES) != (target_epsg in WGS84_EPSG_CODES):
        operation.warnings.append(
            "Generic WGS 84 has no selected realization or coordinate epoch. "
            "Small numerical errors and an NTv2 grid do not establish centimetric "
            "agreement with epoch-specific GNSS coordinates. See each PROJ stage's accuracy."
        )
    if (source_family or target_family) and (
            len(source.axis_info) >= 3 or len(target.axis_info) >= 3):
        operation.warnings.append(
            "The historical datum grid is horizontal-only; preserved CAD Z is not a "
            "verified target-datum ellipsoidal height."
        )
    return operation


def _decode_proxy_graphics(
    entity: Any, cancel: CancellationToken
) -> tuple[list[Any], list[str], list[str]]:
    """Decode complete supported proxy display geometry without silent skips.

    The application-specific object remains archived by the caller. This function
    yields ordinary source-coordinate CAD graphics, not a native custom object.
    """
    from ezdxf.entities import factory
    from ezdxf.lldxf.validator import is_valid_lineweight
    from ezdxf.math import OCS
    from ezdxf.proxygraphic import ProxyGraphic, ProxyGraphicTypes
    from ezdxf.tools.binarydata import BitStream, ByteStream

    data = entity.proxy_graphic
    if not data or len(data) <= 8:
        raise ConversionError(
            "The proxy has no saved display geometry. Open it with its originating CAD application/object enabler and export ordinary CAD entities with proxy graphics enabled."
        )
    decoder = ProxyGraphic(data, doc=entity.doc)
    explicit_lineweight = entity.dxf.hasattr("lineweight")
    for name in ("layer", "color", "linetype", "lineweight", "ltscale", "true_color"):
        if entity.dxf.hasattr(name):
            setattr(decoder, name, entity.dxf.get(name))
    supported = {
        "EXTENTS",
        "CIRCLE",
        "CIRCLE_3P",
        "CIRCULAR_ARC",
        "CIRCULAR_ARC_3P",
        "POLYLINE",
        "POLYGON",
        "MESH",
        "SHELL",
        "TEXT",
        "TEXT2",
        "XLINE",
        "RAY",
        "ATTRIBUTE_COLOR",
        "ATTRIBUTE_LAYER",
        "ATTRIBUTE_LINETYPE",
        "ATTRIBUTE_MARKER",
        "ATTRIBUTE_FILL",
        "ATTRIBUTE_TRUE_COLOR",
        "ATTRIBUTE_LINEWEIGHT",
        "ATTRIBUTE_LTSCALE",
        "ATTRIBUTE_THICKNESS",
        "ATTRIBUTE_PLOT_STYLE_NAME",
        "ATTRIBUTE_MATERIAL",
        "ATTRIBUTE_MAPPER",
        "PUSH_MATRIX",
        "POP_MATRIX",
        "POLYLINE_WITH_NORMALS",
        "LWPOLYLINE",
        "UNICODE_TEXT",
        "UNICODE_TEXT2",
        "ELLIPTIC_ARC",
    }
    chunks = []
    offset = 8
    while offset < len(data):
        cancel.check()
        if len(data) - offset < 8:
            raise ConversionError(f"Truncated proxy command header at byte {offset}.")
        size, opcode = struct.unpack_from("<2L", data, offset)
        if size < 8 or size > len(data) - offset:
            raise ConversionError(
                f"Invalid proxy command length {size} at byte {offset}."
            )
        try:
            name = ProxyGraphicTypes(opcode).name
        except ValueError as exc:
            raise ConversionError(
                f"Unsupported proxy command {opcode} at byte {offset}."
            ) from exc
        if name not in supported:
            raise ConversionError(
                f"Unsupported proxy command {name} at byte {offset}; its geometry cannot be safely omitted."
            )
        chunks.append((offset, name, data[offset + 8 : offset + size]))
        offset += size
    graphics = []
    notes = []
    matrices = []

    def finite(values: Iterable[float], what: str) -> None:
        if not all(math.isfinite(float(value)) for value in values):
            raise ConversionError(f"Non-finite {what} in proxy display geometry.")

    def exact_length(payload: bytes, length: int, name: str) -> None:
        if len(payload) != length:
            raise ConversionError(
                f"Proxy {name} requires {length} payload bytes; found {len(payload)}."
            )

    def end_of_record(stream: Any, name: str) -> None:
        if stream.index != len(stream.buffer):
            raise ConversionError(
                f"Proxy {name} contains missing or undecoded payload bytes."
            )

    def read_points(stream: Any, count: int) -> list[Any]:
        if count < 0 or count > (len(stream.buffer) - stream.index) // 24:
            raise ConversionError("Proxy vertex count exceeds its payload.")
        points = []
        for index in range(count):
            if index % 256 == 0:
                cancel.check()
            point = Vec3(stream.read_vertex())
            finite(point, "vertex")
            points.append(point)
        return points

    def polyline(points: Sequence[Any], closed: bool = False) -> Any:
        if not points:
            raise ConversionError("A proxy polyline contains no display vertices.")
        # Source coordinates are WCS: a 3D polyline preserves elevation, tiny
        # segments, exact repeated vertices and explicit closure without OCS guesses.
        result = factory.new(
            "POLYLINE", dxfattribs={**decoder._build_dxf_attribs(), "flags": 8}
        )
        result.append_vertices(points)
        result.close(closed)
        result.new_seqend()
        return result

    def strict_string(stream: Any, unicode: bool = False) -> str:
        start = stream.index
        step = 2 if unicode else 1
        terminator = b"\0\0" if unicode else b"\0"
        raw = bytes(stream.buffer)
        for end in range(start, len(raw) - step + 1, step):
            if raw[end : end + step] == terminator:
                result = raw[start:end].decode(
                    "utf-16-le" if unicode else decoder.encoding, errors="strict"
                )
                stream.index = stream.align(end + step)
                if stream.index > len(raw):
                    raise ConversionError("Proxy text is missing its padding bytes.")
                return result
        raise ConversionError("Proxy text is missing a string terminator.")

    def text_graphic(payload: bytes, name: str) -> Any:
        stream = ByteStream(payload)
        position, normal, direction = read_points(stream, 3)
        if normal.magnitude == 0 or direction.magnitude == 0:
            raise ConversionError("Proxy text contains a zero direction vector.")
        unicode = name.startswith("UNICODE")
        extended = name.endswith("2")
        if extended:
            text = strict_string(stream, unicode)
            stream.read_struct("<2l")  # stored string length and formatting field
            height, width, oblique, tracking = stream.read_struct("<4d")
            backward, upside_down, vertical, underline, overline = stream.read_struct(
                "<5L"
            )
            if unicode:
                bold, italic, _charset, _pitch = stream.read_struct("<4L")
                typeface = strict_string(stream, True)
                if bold or italic or typeface:
                    notes.append(
                        "Proxy text font face/weight is represented by its stored font file; exact typography depends on installed fonts."
                    )
            font = strict_string(stream, unicode)
            bigfont = strict_string(stream, unicode)
            if vertical or underline or overline or tracking not in (0.0, 1.0, 100.0):
                raise ConversionError(
                    "Proxy text uses vertical, decorated or tracked formatting that cannot be represented completely as ordinary TEXT."
                )
        else:
            height, width, oblique = stream.read_struct("<3d")
            text = strict_string(stream, unicode)
            backward = upside_down = 0
            font = bigfont = ""
        end_of_record(stream, name)
        finite((height, width, oblique), "text dimensions")
        if height <= 0 or width <= 0:
            raise ConversionError("Proxy text has non-positive height or width.")
        normal = normal.normalize()
        direction = direction.normalize()
        if abs(normal.dot(direction)) > 1e-8:
            raise ConversionError(
                "Proxy text baseline is not perpendicular to its normal."
            )
        ocs = OCS(normal)
        attributes = decoder._build_dxf_attribs()
        attributes.update(
            insert=ocs.from_wcs(position),
            extrusion=normal,
            text=text,
            height=height,
            width=width,
            oblique=math.degrees(oblique),
            rotation=ocs.from_wcs(direction).angle_deg,
            text_generation_flag=2 * bool(backward) + 4 * bool(upside_down),
        )
        if font:
            attributes["style"] = decoder._get_style(font, bigfont)
        return factory.new("TEXT", dxfattribs=attributes)

    def lightweight_polyline(payload: bytes) -> Any:
        stream = BitStream(payload, dxfversion=decoder.dxfversion)
        stream.read_unsigned_long()  # encoded payload metadata (format dependent)
        flags = stream.read_bit_short()
        if flags & ~(1 | 2 | 4 | 8 | 16 | 32 | 512 | 1024):
            raise ConversionError("Proxy LWPOLYLINE has unsupported flags.")
        attributes = decoder._build_dxf_attribs()
        for bit, key in ((4, "const_width"), (8, "elevation"), (2, "thickness")):
            if flags & bit:
                attributes[key] = stream.read_bit_double()
        if flags & 1:
            attributes["extrusion"] = Vec3(stream.read_bit_double(3))
        if attributes.get("thickness", 0):
            raise ConversionError(
                "Proxy LWPOLYLINE thickness requires native CAD conversion."
            )
        count = stream.read_bit_long()
        if count <= 0 or count > len(payload) * 8:
            raise ConversionError("Invalid proxy LWPOLYLINE vertex count.")
        bulge_count = stream.read_bit_long() if flags & 16 else 0
        ids_count = width_count = 0
        if decoder.dxfversion >= "AC1024":
            ids_count = stream.read_bit_long() if flags & 1024 else 0
            width_count = stream.read_bit_long() if flags & 32 else 0
        elif flags & (32 | 1024):
            raise ConversionError(
                "Unsupported legacy proxy LWPOLYLINE width/vertex-ID encoding."
            )
        if any(
            value not in (0, count) for value in (bulge_count, ids_count, width_count)
        ):
            raise ConversionError(
                "Proxy LWPOLYLINE bulge, width or vertex-ID count differs from its vertex count."
            )
        vertices = [tuple(stream.read_raw_double(2))]
        for index in range(1, count):
            if index % 256 == 0:
                cancel.check()
            x = stream.read_bit_double_default(default=vertices[-1][0])
            y = stream.read_bit_double_default(default=vertices[-1][1])
            vertices.append((x, y))
        bulges = (
            [stream.read_bit_double() for _ in range(bulge_count)]
            if bulge_count
            else [0.0] * count
        )
        for _ in range(ids_count):
            stream.read_bit_long()
        widths = (
            [
                (stream.read_bit_double(), stream.read_bit_double())
                for _ in range(width_count)
            ]
            if width_count
            else [(0.0, 0.0)] * count
        )
        if (
            stream.bit_index > len(payload) * 8
            or len(payload) * 8 - stream.bit_index >= 32
        ):
            raise ConversionError("Proxy LWPOLYLINE has missing or undecoded data.")
        rows = [
            (x, y, sw, ew, bulge)
            for (x, y), (sw, ew), bulge in zip(vertices, widths, bulges, strict=True)
        ]
        for row in rows:
            finite(row, "polyline coordinates/widths/bulges")
        for key in ("const_width", "elevation", "thickness"):
            if key in attributes:
                finite((attributes[key],), "polyline attributes")
        normal = Vec3(attributes.get("extrusion", (0, 0, 1)))
        finite(normal, "polyline normal")
        if normal.magnitude == 0:
            raise ConversionError("Proxy LWPOLYLINE has a zero normal.")
        result = factory.new("LWPOLYLINE", dxfattribs=attributes)
        result.set_points(rows)
        result.closed = bool(flags & 512)
        if ids_count:
            notes.append(
                "Proxy polyline display vertex identifiers are stored in the source archive; output vertices retain their geometry."
            )
        return result

    for offset, name, payload in chunks:
        cancel.check()
        try:
            result = None
            if name == "EXTENTS":
                exact_length(payload, 48, name)
                finite(struct.unpack("<6d", payload), "extents")
            elif name == "PUSH_MATRIX":
                exact_length(payload, 128, name)
                values = struct.unpack("<16d", payload)
                finite(values, "matrix")
                if matrices:
                    raise ConversionError(
                        "Nested proxy transformation matrices require native CAD conversion."
                    )
                matrix = Matrix44(values)
                matrix.transpose()
                if (
                    any(abs(matrix[index, 3]) > 1e-12 for index in range(3))
                    or abs(matrix[3, 3] - 1.0) > 1e-12
                ):
                    raise ConversionError("A proxy uses a projective display matrix.")
                matrices.append(matrix)
            elif name == "POP_MATRIX":
                exact_length(payload, 0, name)
                if not matrices:
                    raise ConversionError("Unmatched POP_MATRIX in proxy graphics.")
                matrices.pop()
            elif name in {
                "ATTRIBUTE_PLOT_STYLE_NAME",
                "ATTRIBUTE_MATERIAL",
                "ATTRIBUTE_MAPPER",
            }:
                # ODA DWG specification, chapter 29: these commands set display
                # traits, not coordinates or the geometry transformation matrix.
                # Their full bytes remain in the caller's original DXF archive.
                # Do not reinterpret a proxy resource index as a native DXF handle.
                if name == "ATTRIBUTE_PLOT_STYLE_NAME":
                    exact_length(payload, 8, name)
                    style_type, _style_index = struct.unpack("<2L", payload)
                    if style_type not in (0, 1, 2, 3):
                        raise ConversionError(
                            f"Proxy plot-style type {style_type} is not supported."
                        )
                    notes.append(
                        "Proxy ATTRIBUTE_PLOT_STYLE_NAME is archived as appearance "
                        "metadata. Native parent plot-style references are retained; "
                        "per-primitive proxy print styling may differ."
                    )
                elif name == "ATTRIBUTE_MAPPER":
                    exact_length(payload, 28, name)
                    notes.append(
                        "Proxy ATTRIBUTE_MAPPER is archived as appearance metadata. "
                        "Its texture-mapping settings are not applied to replacement "
                        "entities; rendered textures may differ."
                    )
                else:
                    # The embedded material reference is opaque. Only its command
                    # framing is interpreted; material resources are not rebuilt.
                    notes.append(
                        "Proxy ATTRIBUTE_MATERIAL is archived as appearance metadata. "
                        "Native parent material references are retained; "
                        "per-primitive proxy rendering may differ."
                    )
            elif name.startswith("ATTRIBUTE_"):
                exact_length(
                    payload,
                    8 if name in {"ATTRIBUTE_LTSCALE", "ATTRIBUTE_THICKNESS"} else 4,
                    name,
                )
                if name == "ATTRIBUTE_LAYER":
                    index = struct.unpack("<L", payload)[0]
                    if index >= len(decoder.layers):
                        raise ConversionError(
                            "Proxy layer index is outside the drawing layer table."
                        )
                elif name == "ATTRIBUTE_LINETYPE":
                    index = struct.unpack("<L", payload)[0]
                    # ODA documents 32-bit unsigned sentinels. ezdxf's decoder
                    # recognizes the equivalent legacy 15-bit values instead.
                    if index in (0xFFFFFFFE, 0xFFFFFFFF):
                        index = 32766 if index == 0xFFFFFFFE else 32767
                        payload = struct.pack("<L", index)
                    if index not in (32766, 32767) and index + 2 >= len(
                        decoder.linetypes
                    ):
                        raise ConversionError(
                            "Proxy linetype index is outside the drawing linetype table."
                        )
                elif name == "ATTRIBUTE_THICKNESS":
                    thickness = struct.unpack("<d", payload)[0]
                    finite((thickness,), "thickness")
                    if thickness != 0:
                        raise ConversionError(
                            "Non-zero proxy display thickness requires native CAD conversion."
                        )
                elif name == "ATTRIBUTE_LTSCALE":
                    scale = struct.unpack("<d", payload)[0]
                    finite((scale,), "linetype scale")
                    if scale <= 0:
                        raise ConversionError("Proxy linetype scale must be positive.")
                elif (
                    name == "ATTRIBUTE_COLOR" and struct.unpack("<L", payload)[0] > 256
                ):
                    raise ConversionError(
                        "Proxy indexed colour is outside the supported CAD range."
                    )
                if name == "ATTRIBUTE_LINEWEIGHT":
                    explicit_lineweight = True
                    # Negative values are legitimate signed 32-bit traits:
                    # -1 = ByLayer, -2 = ByBlock, -3 = drawing default. The
                    # positive-only VALID_DXF_LINEWEIGHTS table omits them.
                    weight = struct.unpack("<i", payload)[0]
                    if not is_valid_lineweight(weight):
                        notes.append(
                            f"Proxy lineweight {weight} at byte {offset} is not a "
                            "supported CAD lineweight. ByLayer is used for subsequent "
                            "geometry; the original appearance value remains in the "
                            "source archive. Coordinates are unaffected."
                        )
                        payload = struct.pack("<i", -1)
                getattr(decoder, name.lower())(payload)
            elif name in {"POLYLINE", "POLYLINE_WITH_NORMALS", "POLYGON"}:
                stream = ByteStream(payload)
                points = read_points(stream, stream.read_long())
                if name == "POLYLINE_WITH_NORMALS":
                    normal = read_points(stream, 1)[0]
                    if normal.magnitude == 0:
                        raise ConversionError("Proxy polyline has a zero normal.")
                    notes.append(
                        "Proxy polyline vertices are retained in WCS; its auxiliary normal is stored in the source archive."
                    )
                end_of_record(stream, name)
                if name == "POLYGON" and decoder.fill:
                    if (
                        len(points) < 3
                        or max(p.z for p in points) - min(p.z for p in points) > 1e-10
                    ):
                        raise ConversionError(
                            "A filled proxy polygon is degenerate or not horizontal."
                        )
                    result = decoder._filled_polygon(
                        points, decoder._build_dxf_attribs()
                    )
                else:
                    result = polyline(points, closed=name == "POLYGON")
            elif name == "LWPOLYLINE":
                result = lightweight_polyline(payload)
            elif name in {"TEXT", "TEXT2", "UNICODE_TEXT", "UNICODE_TEXT2"}:
                result = text_graphic(payload, name)
            elif name in {"MESH", "SHELL"}:
                stream = ByteStream(payload)
                attributes = decoder._build_dxf_attribs()
                if name == "MESH":
                    rows, columns = stream.read_struct("<2L")
                    if rows < 2 or columns < 2:
                        raise ConversionError(
                            "Proxy mesh has invalid row/column counts."
                        )
                    points = read_points(stream, rows * columns)
                    result = factory.new(
                        "POLYLINE",
                        dxfattribs={
                            **attributes,
                            "flags": 16,
                            "m_count": rows,
                            "n_count": columns,
                        },
                    )
                    result.append_vertices(points)
                else:
                    points = read_points(stream, stream.read_long())
                    entry_count = stream.read_long()
                    if entry_count > (len(payload) - stream.index) // 4:
                        raise ConversionError(
                            "Proxy shell face count exceeds the payload."
                        )
                    consumed = 0
                    faces = []
                    while consumed < entry_count:
                        cancel.check()
                        count = stream.read_signed_long()
                        if count not in (3, 4) or count > entry_count - consumed - 1:
                            raise ConversionError(
                                "Proxy shell requires triangular/quadrilateral faces without holes."
                            )
                        indices = [stream.read_long() for _ in range(count)]
                        if any(index >= len(points) for index in indices):
                            raise ConversionError(
                                "Proxy shell face references a missing vertex."
                            )
                        faces.append(indices)
                        consumed += count + 1
                    if not faces:
                        raise ConversionError("Proxy shell has no faces.")
                    result = factory.new(
                        "POLYLINE", dxfattribs={**attributes, "flags": 64}
                    )
                    # append_faces() merges positions rounded to six decimals.
                    # Keep the source indices and every vertex, including tiny
                    # or intentionally coincident mesh features.
                    result.append_vertices(points, dxfattribs={"flags": 192})
                    for indices in faces:
                        face_attributes = {"flags": 128}
                        face_attributes.update(
                            {
                                f"vtx{index}": value + 1
                                for index, value in enumerate(indices)
                            }
                        )
                        result.append_vertex((0, 0, 0), dxfattribs=face_attributes)
                        # append_vertex() adds the parent mesh's coordinate
                        # flags; a face record must contain indices only.
                        result.vertices[-1].dxf.flags = 128
                    result.update_count(len(points), len(faces))
                trailing = payload[stream.index :]
                if trailing and (len(trailing) not in (8, 12) or any(trailing)):
                    raise ConversionError(
                        "Proxy mesh/shell has unsupported per-face/per-edge traits or corrupt trailing data."
                    )
            else:
                sizes = {
                    "CIRCLE": (56,),
                    "CIRCLE_3P": (72,),
                    "CIRCULAR_ARC": (88, 92),
                    "CIRCULAR_ARC_3P": (72, 76),
                    "ELLIPTIC_ARC": (88,),
                    "XLINE": (48,),
                    "RAY": (48,),
                }
                if len(payload) not in sizes[name]:
                    raise ConversionError(
                        f"Proxy {name} has an unexpected payload length."
                    )
                numeric_bytes = (
                    len(payload) - 4 if len(payload) in (76, 92) else len(payload)
                )
                values = struct.unpack(
                    f"<{numeric_bytes // 8}d", payload[:numeric_bytes]
                )
                finite(values, name)
                if (
                    len(payload) in (76, 92)
                    and struct.unpack("<L", payload[-4:])[0] != 0
                ):
                    raise ConversionError(
                        "The proxy arc uses an unsupported arc-type flag."
                    )
                if name == "CIRCULAR_ARC":
                    center = Vec3(values[:3])
                    radius = values[3]
                    normal = Vec3(values[4:7])
                    direction = Vec3(values[7:10])
                    sweep = values[10]
                    if radius <= 0 or normal.magnitude == 0 or direction.magnitude == 0:
                        raise ConversionError(
                            "Proxy arc radius or direction is invalid."
                        )
                    if sweep == 0 or abs(sweep) > math.tau + 1e-12:
                        raise ConversionError(
                            "Proxy arc sweep is zero or exceeds a full circle."
                        )
                    normal = normal.normalize()
                    direction = direction.normalize()
                    if abs(normal.dot(direction)) > 1e-8:
                        raise ConversionError(
                            "Proxy arc start direction is not in its plane."
                        )
                    if sweep < 0:
                        normal = -normal
                    ocs = OCS(normal)
                    attributes = decoder._build_dxf_attribs()
                    attributes.update(
                        center=ocs.from_wcs(center), radius=radius, extrusion=normal
                    )
                    if abs(abs(sweep) - math.tau) <= 1e-12:
                        result = factory.new("CIRCLE", dxfattribs=attributes)
                    else:
                        start_angle = ocs.from_wcs(direction).angle_deg
                        attributes.update(
                            start_angle=start_angle,
                            end_angle=start_angle + math.degrees(abs(sweep)),
                        )
                        result = factory.new("ARC", dxfattribs=attributes)
                elif name in {"CIRCLE_3P", "CIRCULAR_ARC_3P"}:
                    points = [Vec3(values[index : index + 3]) for index in (0, 3, 6)]
                    if max(p.z for p in points) - min(p.z for p in points) > 1e-10:
                        raise ConversionError(
                            "A tilted three-point proxy arc/circle requires native CAD conversion."
                        )
                    result = getattr(decoder, name.lower())(payload)
                    result.dxf.center = Vec3(
                        result.dxf.center.x, result.dxf.center.y, points[0].z
                    )
                    if name == "CIRCULAR_ARC_3P":
                        winding = (points[1] - points[0]).cross(points[2] - points[0]).z
                        if winding == 0:
                            raise ConversionError(
                                "Proxy three-point arc points are collinear."
                            )
                        normal = Vec3(0, 0, 1 if winding > 0 else -1)
                        ocs = OCS(normal)
                        center = result.dxf.center
                        result.dxf.center = ocs.from_wcs(center)
                        result.dxf.extrusion = normal
                        result.dxf.start_angle = ocs.from_wcs(
                            points[0] - center
                        ).angle_deg
                        result.dxf.end_angle = ocs.from_wcs(
                            points[2] - center
                        ).angle_deg
                else:
                    result = getattr(decoder, name.lower())(payload)
                if name == "CIRCLE" and (
                    values[3] <= 0 or Vec3(values[4:7]).magnitude == 0
                ):
                    raise ConversionError("Proxy circle radius or normal is invalid.")
                if name == "ELLIPTIC_ARC" and (
                    values[6] <= 0
                    or values[7] <= 0
                    or values[7] > values[6]
                    or Vec3(values[3:6]).magnitude == 0
                ):
                    raise ConversionError("Proxy ellipse axes or normal are invalid.")
            if result is not None:
                if explicit_lineweight:
                    # ezdxf omits -3 from its generated attributes, although a
                    # missing native DXF value means ByLayer (-1), not Default.
                    result.dxf.lineweight = decoder.lineweight
                if matrices:
                    try:
                        result.transform(matrices[-1])
                    except Exception as exc:
                        from ezdxf.math import NonUniformScalingError

                        if isinstance(
                            exc, NonUniformScalingError
                        ) and result.dxftype() in {"CIRCLE", "ARC"}:
                            from ezdxf.entities import Ellipse

                            result = Ellipse.from_arc(result).transform(matrices[-1])
                        else:
                            raise ConversionError(
                                f"The proxy display matrix cannot safely transform {result.dxftype()}: {type(exc).__name__}: {exc}"
                            ) from exc
                graphics.append(result)
                decoder.fill = False
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                f"Invalid proxy {name} command at byte {offset}: {type(exc).__name__}: {exc}"
            ) from exc
    if matrices:
        raise ConversionError(
            "The proxy has an unbalanced transformation matrix stack."
        )
    if not graphics:
        raise ConversionError(
            "The proxy contains no usable display geometry; export ordinary CAD entities from its originating application."
        )
    return graphics, [name for _, name, _ in chunks], list(dict.fromkeys(notes))


def _lwpolyline_rows(entity: Any) -> Any:
    """Read-only float64 XY/start-width/end-width/bulge rows (ezdxf 1.4 API).

    Never mutate the backing array: entity.set_points() owns geometry updates.
    The public iterator remains a fallback for other compatible ezdxf releases.
    """
    points = getattr(entity, "lwpoints", None)
    values = getattr(points, "values", None)
    if isinstance(values, np.ndarray) and values.ndim == 2 and values.shape[1] == 5:
        return values
    return np.asarray(list(entity), dtype=np.float64).reshape(-1, 5)


def _drawing_area_of_interest(
    document: Any, source_crs: Any, *, tolerate_outliers: bool = False
) -> tuple[float, float, float, float] | None:
    """Advisory operation-selection extent; never a substitute for each-point checks."""
    from ezdxf.math import BoundingBox

    box = BoundingBox()
    for entity in document.modelspace():
        try:
            part = _fast_entity_box(entity)
            if part.has_data and all(math.isfinite(v) for p in (part.extmin, part.extmax) for v in p):
                box.extend((part.extmin, part.extmax))
        except Exception:
            continue  # Unsupported boxes do not exclude the object's conversion.
    if not box.has_data:
        return None
    code = source_crs.to_epsg()
    family = GRID_FAMILY_BY_EPSG.get(code)
    geographic = CRS.from_epsg(GRID_FAMILIES[family][0]) if family else source_crs.geodetic_crs
    if source_crs.is_geocentric:
        geographic = CRS.from_epsg({4936: 4937, 5011: 5012}[code])
    else:
        geographic = geographic.to_2d()
    transformer = Transformer.from_crs(_supported_bonne(source_crs), geographic, always_xy=True)
    coordinates = []
    for x in (box.extmin.x, box.center.x, box.extmax.x):
        for y in (box.extmin.y, box.center.y, box.extmax.y):
            try:
                lon, lat, *_ = transformer.transform(x, y, box.center.z, errcheck=True)
            except Exception as exc:
                if tolerate_outliers:
                    return None  # Real coordinates are checked by their owning entity.
                raise CoordinateTransformationError(
                    f"The source drawing extent cannot be interpreted in {source_crs.name}: {exc}"
                ) from exc
            if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
                if tolerate_outliers:
                    return None
                raise CoordinateTransformationError("Invalid geographic source extent; verify source EPSG and coordinate units.")
            coordinates.append((lon, lat))
    west, east = min(p[0] for p in coordinates), max(p[0] for p in coordinates)
    south, north = min(p[1] for p in coordinates), max(p[1] for p in coordinates)
    if east - west > 180:
        return None
    return max(-180.0, west - 0.02), max(-90.0, south - 0.02), min(180.0, east + 0.02), min(90.0, north + 0.02)


class _TrackedOutputLayout:
    """Record outputs before binding so a failed explosion can be discarded."""

    def __init__(self, layout: Any, add_output: Callable[[Any, Any], None]) -> None:
        self.layout = layout
        self.add_output = add_output

    def add_entity(self, entity: Any) -> None:
        self.add_output(self.layout, entity)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.layout, name)


class DrawingReprojector:
    """Reproject CAD geometry and explicitly account for unsupported content."""

    CURVE_TYPES = frozenset(
        {
            "ARC",
            "CIRCLE",
            "ELLIPSE",
            "SPLINE",
            "HELIX",
            "LWPOLYLINE",
        }
    )
    COMPOSITE_TYPES = frozenset({"INSERT", "DIMENSION"})
    EXACT_POINT_TYPES = frozenset({"LINE", "POINT", "3DFACE", "SOLID", "TRACE"})
    NON_GEOMETRIC_TYPES = frozenset({"GEODATA", "XRECORD"})
    COUNTER_FIELDS = ("transformed", "approximated", "local_affine", "exploded", "unresolved", "omitted")
    ARCHIVE_FIELDS = ("issues", "fitted_polyline_sources", "proxy_entity_sources",
                      "hatch_boundary_sources", "auxiliary_coordinate_repairs")

    def __init__(
        self,
        document: Any,
        job: ConversionJob,
        result: FileResult,
        cancel: CancellationToken,
        log: LogCallback,
        progress: ProgressCallback | None = None,
    ) -> None:
        self.doc = document
        if job.curve_tolerance is None:
            job = replace(job, curve_tolerance=default_curve_tolerance(job.source_epsg))
        if (not math.isfinite(job.curve_tolerance) or job.curve_tolerance <= 0
                or not math.isfinite(job.reprojection_tolerance_m)
                or job.reprojection_tolerance_m <= 0):
            raise ConversionError("Both geometry tolerances must be finite and positive.")
        self.job = job
        self.result = result
        self.cancel = cancel
        self.log = log
        self.progress = progress or (lambda _value, _message: None)
        self._progress_last_time = 0.0
        self._progress_value = 0.0
        self._progress_layout_base = 0.06
        self._progress_layout_span = 0.82
        self._progress_completed = 0
        self._progress_total = 1
        self._progress_current_weight = 1.0
        self._entity_label = "Preparing geometry"
        self._cache: OrderedDict[tuple[float, float, float], Any] = OrderedDict()
        self._matrix_cache: OrderedDict[tuple[float, float, float], Any] = OrderedDict()
        self._grid_failure_cache: OrderedDict[tuple[float, float, float], Any] = OrderedDict()
        self._grid_failure_cache_hits = 0
        self._cache_hits = 0
        self._matrix_cache_hits = 0
        self._edge_cache: dict[tuple[Any, Any], tuple[Any, Any, Any, Any]] = {}
        self._edge_cache_hits = 0
        self._defer_deletion = False
        self._deferred_layouts: dict[int, Any] = {}
        self._omission_log_count = 0
        self._batch_calls = 0
        self._linear_polyline_batches = 0
        self._coordinate_role = "geometry coordinate"
        self._prepared_proxy_handles: set[str] = set()
        self._active_outputs: list[Any] = []
        self._active_origin: tuple[str, str, str] | None = None
        self._output_origins: dict[str, tuple[str, str, str]] = {}
        self.source_crs = CRS.from_epsg(job.source_epsg)
        self.target_crs = CRS.from_epsg(job.target_epsg)
        self.coordinate_operation = build_coordinate_operation(
            job.source_epsg, job.target_epsg, job.allow_ballpark, job.grid_directory,
            allow_degraded=job.allow_degraded,
            area_of_interest=_drawing_area_of_interest(
                document, self.source_crs, tolerate_outliers=job.skip_outside_grid and not job.strict_unresolved
            ),
        )
        self.transformer = self.coordinate_operation
        self.use_3d = (
            len(self.source_crs.axis_info) >= 3 or len(self.target_crs.axis_info) >= 3
        )
        self._scale_display_sizes = (
            not self.source_crs.is_geocentric and not self.target_crs.is_geocentric
            and not self.source_crs.equals(self.target_crs)
        )
        self._reference_source_point: Any = None
        self._point_transform_count = 0
        self._roundtrip_samples: list[dict[str, Any]] = []
        self._one_sided_derivatives = 0
        self._source_geod = self.source_crs.get_geod()
        self._target_geographic = bool(self.target_crs.is_geographic)
        self._metric_ellipsoids = []
        for crs in (self.target_crs, self.source_crs):
            ellipsoid = crs.ellipsoid
            a, b = ellipsoid.semi_major_metre, ellipsoid.semi_minor_metre
            self._metric_ellipsoids.append((bool(crs.is_geographic), a, 1.0 - (b / a) ** 2))


    @property
    def operation_description(self) -> str:
        return getattr(self.transformer, "description", "coordinate transformation")

    @property
    def operation_accuracy(self) -> float | None:
        accuracy = getattr(self.transformer, "accuracy", None)
        return float(accuracy) if accuracy is not None and accuracy >= 0 else None

    def transform_point(self, value: Any) -> Any:
        x, y, z = _point_tuple(value)
        key = (x, y, z)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache_hits += 1
            self._cache.move_to_end(key)
            return cached
        failure = self._grid_failure_cache.get(key)
        if failure is not None:
            self._grid_failure_cache_hits += 1
            self._grid_failure_cache.move_to_end(key)
            raise GridCoverageError(
                f"{failure[0]}\nSource WCS EPSG:{self.job.source_epsg}: "
                f"X={x:.12g}, Y={y:.12g}, Z={z:.12g}; role: {self._coordinate_role}.",
                details={**failure[1], "source_epsg": self.job.source_epsg,
                         "source_wcs": [x, y, z], "coordinate_role": self._coordinate_role},
            )
        try:
            if self.use_3d:
                tx, ty, tz = self.transformer.transform(x, y, z, errcheck=True)
            else:
                tx, ty = self.transformer.transform(x, y, errcheck=True)
                tz = z if self.job.preserve_z else 0.0
        except CoordinateTransformationError as exc:
            details = ({"details": {**exc.details, "source_epsg": self.job.source_epsg,
                        "source_wcs": [x, y, z], "coordinate_role": self._coordinate_role}}
                       if isinstance(exc, GridCoverageError) else {})
            message = (f"{exc}\nSource WCS EPSG:{self.job.source_epsg}: "
                       f"X={x:.12g}, Y={y:.12g}, Z={z:.12g}; role: {self._coordinate_role}.")
            if isinstance(exc, GridCoverageError):
                self._grid_failure_cache[key] = (str(exc), dict(exc.details))
                if len(self._grid_failure_cache) > EDGE_CACHE_LIMIT:
                    self._grid_failure_cache.popitem(last=False)
            raise type(exc)(message, **details) from exc
        if not all(math.isfinite(item) for item in (tx, ty, tz)):
            raise CoordinateTransformationError(f"Non-finite result from ({x}, {y}, {z}).")
        if self._reference_source_point is None:
            self._reference_source_point = Vec3(x, y, z)
        self._point_transform_count += 1
        if len(self._roundtrip_samples) < 128 and (
                self._point_transform_count <= 32 or self._point_transform_count % 1024 == 0):
            values = (tx, ty, tz) if self.use_3d else (tx, ty)
            try:
                reverse = self.transformer.transform(*values, direction="INVERSE")
                if self.source_crs.is_geographic:
                    _, _, horizontal = self._source_geod.inv(x, y, reverse[0], reverse[1])
                else:
                    horizontal = math.hypot(reverse[0] - x, reverse[1] - y)
                vertical = abs(reverse[2] - z) if self.use_3d else 0.0
                self._roundtrip_samples.append({
                    "source": [x, y, z], "target": [tx, ty, tz],
                    "horizontal_closure_m": abs(horizontal), "vertical_closure_m": vertical,
                })
            except CoordinateTransformationError as exc:
                self._roundtrip_samples.append({"source": [x, y, z], "inverse_check_error": str(exc)})
        result = Vec3(float(tx), float(ty), float(tz))
        self._cache[key] = result
        if len(self._cache) > POINT_CACHE_LIMIT:
            self._cache.popitem(last=False)
        return result

    def _emit_progress(self, value: float, message: str, *, force: bool = False) -> None:
        self.cancel.check()
        value = min(1.0, max(self._progress_value, value))
        self._progress_value = value
        now = time.monotonic()
        if force or now - self._progress_last_time >= 0.12:
            self.progress(value, message)
            self._progress_last_time = now

    def _entity_progress(self, fraction: float) -> None:
        complete = self._progress_completed + min(0.99, max(0.0, fraction)) * self._progress_current_weight
        value = self._progress_layout_base + self._progress_layout_span * complete / max(1, self._progress_total)
        self._emit_progress(value, self._entity_label)

    def transform_points(self, vertices: Iterable[Any]) -> list[Any]:
        """Checked array batches; original ordering, repeats and all Z values survive."""
        points = [Vec3(p) for p in vertices]
        if len(points) < 16:
            return [self.transform_point(p) for p in points]
        output = []
        for begin in range(0, len(points), TRANSFORM_BATCH_SIZE):
            self.cancel.check()
            chunk = points[begin:begin + TRANSFORM_BATCH_SIZE]
            # Keep the diagnostic closure sample schedule for scalar evaluations.
            if len(self._roundtrip_samples) < 32:
                n = min(32 - len(self._roundtrip_samples), len(chunk))
                for point in chunk[:n]:
                    self.transform_point(point)
            missing = list(dict.fromkeys(tuple(p) for p in chunk if tuple(p) not in self._cache))
            if missing:
                source = np.asarray(missing, dtype=np.float64)
                self._batch_calls += 1
                try:
                    mapped = self.transformer.transform_many(source if self.use_3d else source[:, :2])
                except CoordinateTransformationError:
                    # Obtain the same source-coordinate/role diagnostic as scalar processing.
                    for point in missing:
                        self.transform_point(point)
                    raise
                self._point_transform_count += len(missing)
                for index, key in enumerate(missing):
                    z = mapped[index, 2] if self.use_3d else key[2] if self.job.preserve_z else 0.0
                    self._cache[key] = Vec3(mapped[index, 0], mapped[index, 1], z)
                    if self._reference_source_point is None:
                        self._reference_source_point = Vec3(key)
                while len(self._cache) > POINT_CACHE_LIMIT:
                    self._cache.popitem(last=False)
            for point in chunk:
                key = tuple(point)
                cached = self._cache.get(key)
                output.append(cached if cached is not None else self.transform_point(point))
            self._emit_progress(self._progress_value, self._entity_label)
        return output

    def _prime_edges(self, vertices: Sequence[Any], closed: bool = False) -> None:
        """Batch acceptance for consecutive edges without changing source topology."""
        if len(vertices) < 16:
            return
        count = len(vertices) if closed else len(vertices) - 1
        self._prime_edge_pairs([(Vec3(vertices[i]), Vec3(vertices[(i + 1) % len(vertices)]))
                                for i in range(count)])

    def _prime_edge_pairs(self, pairs: Sequence[tuple[Any, Any]]) -> None:
        """Cache only clearly accepted edges, using all three float64 quarter probes.

        Curved, long, wrap-crossing and threshold-adjacent edges retain scalar
        adaptive refinement. Exact keys prohibit rounding or spatial bucketing.
        """
        for begin in range(0, len(pairs), 256):
            self.cancel.check()
            edges = pairs[begin:begin + 256]
            probes = [p for a, b in edges
                      for p in (a, b, a.lerp(b, .25), a.lerp(b, .5), a.lerp(b, .75))]
            mapped = self.transform_points(probes)
            array = np.asarray([tuple(p) for p in mapped], dtype=np.float64).reshape(-1, 5, 3)
            start, end, interior = array[:, 0, :], array[:, 1, :], array[:, 2:, :]
            factors = np.ones_like(interior)
            if self._target_geographic:
                _, semi_major, e2 = self._metric_ellipsoids[0]
                phi = np.deg2rad(interior[:, :, 1])
                denominator = 1 - e2 * np.sin(phi) ** 2
                factors[:, :, 0] = np.maximum(1e-9, math.pi / 180 * semi_major *
                                              np.abs(np.cos(phi)) / np.sqrt(denominator))
                factors[:, :, 1] = math.pi / 180 * semi_major * (1 - e2) / denominator ** 1.5
            v = (end - start)[:, None, :] * factors
            w = (interior - start[:, None, :]) * factors
            denominator = np.sum(v * v, axis=2)
            fraction = np.zeros_like(denominator)
            np.divide(np.sum(w * v, axis=2), denominator, out=fraction, where=denominator != 0)
            fraction = np.clip(fraction, 0.0, 1.0)
            error = np.sqrt(np.sum((w - v * fraction[:, :, None]) ** 2, axis=2)).max(axis=1)
            for i, (a, b) in enumerate(edges):
                scales = self._metric_factors(a.lerp(b, .5), source=True)
                length = math.sqrt(sum((delta * scale) ** 2
                                      for delta, scale in zip(b - a, scales, strict=True)))
                wrap = self._target_geographic and abs(start[i, 0] - end[i, 0]) > 180
                # A conservative numerical margin sends threshold cases to scalar checks.
                if (not wrap and error[i] <= self.job.reprojection_tolerance_m - 1e-10
                        and length <= 1000 - 1e-9):
                    if len(self._edge_cache) >= EDGE_CACHE_LIMIT:
                        self._edge_cache.clear()
                    self._edge_cache[(tuple(a), tuple(b))] = (a, b, mapped[i * 5], mapped[i * 5 + 1])

    def _local_matrix(self, anchor: Any) -> Any:
        """Centred local Jacobian with separate angular XY and metric Z steps.

        Only a derivative probe may use a one-sided difference at a grid edge. The
        anchor and all actual geometry coordinates still require the full operation.
        """
        p = Vec3(anchor)
        key = tuple(p)
        if key in self._matrix_cache:
            self._matrix_cache_hits += 1
            self._matrix_cache.move_to_end(key)
            return self._matrix_cache[key]
        p0 = self.transform_point(p)
        horizontal_step = 1e-5 if self.source_crs.is_geographic else 0.25

        def derivative(axis: Any, step: float) -> Any:
            plus = minus = None
            for sign in (1, -1):
                try:
                    transformed = self.transform_point(p + axis * (sign * step))
                except CoordinateTransformationError:
                    continue
                if sign == 1:
                    plus = transformed
                else:
                    minus = transformed
            if plus is not None and minus is not None:
                return (plus - minus) / (2 * step)
            self._one_sided_derivatives += 1
            if plus is not None:
                return (plus - p0) / step
            if minus is not None:
                return (p0 - minus) / step
            raise CoordinateTransformationError("No valid derivative probe is available at the entity anchor.")

        ux = derivative(Vec3(1, 0, 0), horizontal_step)
        uy = derivative(Vec3(0, 1, 0), horizontal_step)
        uz = (derivative(Vec3(0, 0, 1), 0.25) if self.use_3d else
              Vec3(0, 0, 1 if self.job.preserve_z else 0))
        if ux.magnitude < 1e-15 or uy.magnitude < 1e-15:
            raise ConversionError("Local CRS derivative is singular at this entity.")
        matrix = Matrix44.translate(-p.x, -p.y, -p.z) @ Matrix44.ucs(ux=ux, uy=uy, uz=uz, origin=p0)
        self._matrix_cache[key] = matrix
        if len(self._matrix_cache) > MATRIX_CACHE_LIMIT:
            self._matrix_cache.popitem(last=False)
        return matrix

    def _metric_factors(self, point: Any, *, source: bool = False) -> tuple[float, float, float]:
        """Cache CRS metadata, not position-dependent scale: every latitude is evaluated."""
        geographic, a, e2 = self._metric_ellipsoids[int(source)]
        if not geographic:
            return 1.0, 1.0, 1.0
        phi = math.radians(point.y)
        denominator = 1 - e2 * math.sin(phi) ** 2
        longitude = math.pi / 180 * a * abs(math.cos(phi)) / math.sqrt(denominator)
        latitude = math.pi / 180 * a * (1 - e2) / denominator ** 1.5
        return max(longitude, 1e-9), latitude, 1.0


    def _chord_error_m(self, point: Any, start: Any, end: Any) -> float:
        fx, fy, fz = self._metric_factors(point)
        vx, vy, vz = (end.x - start.x) * fx, (end.y - start.y) * fy, (end.z - start.z) * fz
        wx, wy, wz = (point.x - start.x) * fx, (point.y - start.y) * fy, (point.z - start.z) * fz
        length_squared = vx * vx + vy * vy + vz * vz
        fraction = (max(0.0, min(1.0, (wx * vx + wy * vy + wz * vz) / length_squared))
                    if length_squared else 0.0)
        return math.sqrt((wx - vx * fraction) ** 2 + (wy - vy * fraction) ** 2
                         + (wz - vz * fraction) ** 2)

    def _edge_samples(self, start: Any, end: Any) -> list[tuple[float, Any, Any]]:
        """Sample a source straight edge, resolving nonlinear target-coordinate bending.

        Quarter, midpoint and three-quarter tests plus a 1 km source-spacing cap
        prevent endpoint-only reprojection of long engineering linework. The metric
        error is an adaptive sampling criterion, not a proof for arbitrary mappings.
        """
        start, end = Vec3(start), Vec3(end)
        self.cancel.check()
        accepted = self._edge_cache.get((tuple(start), tuple(end)))
        if accepted is not None:
            self._edge_cache_hits += 1
            return [(0.0, accepted[0], accepted[2]), (1.0, accepted[1], accepted[3])]
        cache: dict[float, tuple[Any, Any]] = {}

        def sample(t: float) -> tuple[Any, Any]:
            if t not in cache:
                self.cancel.check()
                if len(cache) >= MAX_CURVE_VERTICES:
                    raise ConversionError("Adaptive reprojection exceeded the per-edge vertex limit.")
                p = start if t == 0 else end if t == 1 else start.lerp(end, t)
                cache[t] = (p, self.transform_point(p))
            return cache[t]

        output = [(0.0, *sample(0.0))]
        pending = [(0.0, 1.0, 0)]
        while pending:
            lo, hi, depth = pending.pop()
            p, a = sample(lo)
            q, b = sample(hi)
            if self.target_crs.is_geographic and abs(a.x - b.x) > 180:
                raise ConversionError("An edge crosses the longitude wrap; split the drawing at the antimeridian.")
            if p == q:
                output.append((hi, q, b))
                continue
            probes = [sample(lo + (hi - lo) * f)[1] for f in (0.25, 0.5, 0.75)]
            error = max(self._chord_error_m(v, a, b) for v in probes)
            factors = self._metric_factors(p.lerp(q, 0.5), source=True)
            length = math.sqrt(sum((v * f) ** 2 for v, f in zip(q - p, factors, strict=True)))
            if error <= self.job.reprojection_tolerance_m and length <= 1000:
                output.append((hi, q, b))
            else:
                if depth >= 24:
                    raise ConversionError("Adaptive reprojection did not converge; check units, coverage and tolerance.")
                mid = (lo + hi) / 2
                pending.extend(((mid, hi, depth + 1), (lo, mid, depth + 1)))
        return output


    def _transform_path(self, vertices: Iterable[Any], closed: bool) -> list[Any]:
        source = [Vec3(p) for p in vertices]
        if not source:
            return []
        output = [self.transform_point(source[0])]
        pairs = list(zip(source, source[1:]))
        if closed and len(source) > 1:
            pairs.append((source[-1], source[0]))
        for index, (start, end) in enumerate(pairs):
            if index % 256 == 0:
                block = pairs[index:index + 256]
                if len(block) >= 16:
                    self._prime_edges([block[0][0]] + [pair[1] for pair in block])
                self._entity_progress(0.8 * index / max(1, len(pairs)))
            output.extend(row[2] for row in self._edge_samples(start, end)[1:])
            if len(output) > MAX_CURVE_VERTICES:
                raise ConversionError("The curve exceeds the output vertex limit.")
        if closed and len(output) > 1 and output[0] == output[-1]:
            output.pop()
        return output


    def _perpendicular_width_scale(self, anchor: Any, tangent: Any, ocs: Any) -> float:
        """Width scale = |det(A)|/|A t|, not |A n| under anisotropy/shear."""
        matrix = self._local_matrix(anchor)
        u, v = matrix.transform_direction(ocs.ux), matrix.transform_direction(ocs.uy)
        determinant = abs(u.x * v.y - u.y * v.x)
        t = Vec3(tangent)
        length = math.hypot(t.x, t.y)
        if length == 0:
            scale = math.sqrt(determinant)
        else:
            mapped = u * (t.x / length) + v * (t.y / length)
            scale = determinant / math.hypot(mapped.x, mapped.y)
        if not math.isfinite(scale) or scale <= 0:
            raise ConversionError("Polyline width has a singular horizontal mapping.")
        return scale


    def _collect_curve_vertices(self, vertices: Iterable[Any]) -> list[Any]:
        """Bound work and memory while consuming a native curve evaluator."""
        output = []
        for index, point in enumerate(vertices):
            if index >= MAX_CURVE_VERTICES:
                raise ConversionError("Curve flattening exceeds the per-object vertex limit.")
            if index % 256 == 0:
                self.cancel.check()
            output.append(Vec3(point))
        return output

    def _arc_vertices(self, center: Any, radius: float, start: float,
                      sweep: float) -> list[Any]:
        """Evaluate a true circular arc; angles are radians, sagitta is source units."""
        radius = abs(float(radius))
        if not all(math.isfinite(v) for v in (radius, start, sweep)) or radius <= 0:
            raise ConversionError("A circular boundary has an invalid radius or angle.")
        step = 4 * math.asin(math.sqrt(min(1.0, self.job.curve_tolerance / (2 * radius))))
        if step <= 0 or abs(sweep) > step * (MAX_CURVE_VERTICES - 1):
            raise ConversionError("The circular boundary exceeds the vertex limit at this tolerance.")
        count = max(8, math.ceil(abs(sweep) / step))
        center = Vec3(center)
        return self._collect_curve_vertices(
            center + Vec3(radius * math.cos(start + sweep * i / count),
                          radius * math.sin(start + sweep * i / count), 0)
            for i in range(count + 1)
        )

    def _ellipse_vertices(self, tool: Any) -> tuple[list[Any], bool]:
        """Analytic ellipse sampling with a source-space chord-error bound.

        A nonzero start plus one turn remains a full ellipse; a tiny nonzero
        sweep remains an arc. Equal raw parameters are a degenerate interval,
        never guessed to mean a complete ellipse. The radius bound is the
        operator norm of the two axis vectors, so tilted ellipses are supported.
        """
        start, end = float(tool.start_param), float(tool.end_param)
        center, major, minor = Vec3(tool.center), Vec3(tool.major_axis), Vec3(tool.minor_axis)
        if not all(math.isfinite(v) for v in (*center, *major, *minor, start, end)):
            raise ConversionError("Ellipse parameters or axes are non-finite.")
        if major.magnitude == 0 or minor.magnitude == 0:
            raise ConversionError("Ellipse has a zero-length axis.")
        delta = end - start
        if delta == 0:
            raise ConversionError(
                f"Ellipse has identical start/end parameters ({start:.17g}); "
                "a full turn cannot be inferred from a zero-span interval.")
        turn_error = 8 * max(math.ulp(start), math.ulp(end), math.ulp(math.tau))
        closed = abs(abs(delta) - math.tau) <= turn_error
        if abs(delta) > math.tau + turn_error:
            raise ConversionError("Ellipse parameter interval exceeds one turn.")
        sweep = math.tau if closed else (delta if delta > 0 else delta % math.tau)
        if sweep <= 0:
            raise ConversionError("Ellipse has no positive counter-clockwise parameter span.")
        # Largest eigenvalue of A.T A, A=[major, minor]. No equal-axis assumption.
        aa, bb, ab = major.dot(major), minor.dot(minor), major.dot(minor)
        radius = math.sqrt((aa + bb + math.hypot(aa - bb, 2 * ab)) * .5)
        step = 4 * math.asin(math.sqrt(min(1.0, self.job.curve_tolerance / (2 * radius))))
        if step <= 0 or sweep > step * (MAX_CURVE_VERTICES - 1):
            raise ConversionError("Ellipse exceeds the vertex limit at the selected tolerance.")
        count = max(8, math.ceil(sweep / step))
        angle = start % math.tau
        vertices = self._collect_curve_vertices(
            center + major * math.cos(angle + sweep * i / count)
                   + minor * math.sin(angle + sweep * i / count)
            for i in range(count + 1))
        if closed:
            vertices[-1] = vertices[0]  # exact topological closure, not a rounded interior point
        return vertices, closed

    def _source_curve_vertices(self, entity: Any) -> tuple[list[Any], bool]:
        """Use analytic/BSpline evaluators, never a cubic-circle surrogate."""
        kind = entity.dxftype()
        tolerance = self.job.curve_tolerance
        if kind in {"ARC", "CIRCLE"}:
            closed = kind == "CIRCLE"
            start = 0.0 if closed else math.radians(entity.dxf.start_angle)
            sweep = math.tau if closed else math.radians(
                (entity.dxf.end_angle - entity.dxf.start_angle) % 360)
            points = self._arc_vertices(entity.dxf.center, entity.dxf.radius, start, sweep)
            vertices = [entity.ocs().to_wcs(point) for point in points]
        elif kind == "ELLIPSE":
            vertices, closed = self._ellipse_vertices(entity.construction_tool())
        elif kind == "SPLINE":
            vertices = self._collect_curve_vertices(
                entity.construction_tool().flattening(tolerance, segments=8))
            closed = bool(entity.closed)
        else:
            path = make_path(entity)
            vertices = self._collect_curve_vertices(path.flattening(distance=tolerance, segments=8))
            closed = bool(path.is_closed)
        return vertices, closed

    def _hatch_source_loops(self, boundary: Any, ocs: Any,
                            elevation: float) -> list[tuple[list[Any], bool]]:
        """Sample native hatch edges analytically and keep compound loops separate."""
        from ezdxf.entities.boundary_paths import (
            ArcEdge, EllipseEdge, LineEdge, PolylinePath, SplineEdge,
        )
        from ezdxf.math import fit_points_to_cad_cv

        def wcs(point: Any) -> Any:
            return ocs.to_wcs((point[0], point[1], elevation))

        def coincident(a: Any, b: Any) -> bool:
            # Floating-point endpoint noise only; no relative map-coordinate test.
            magnitude = max(abs(v) for v in (*a, *b))
            return a.isclose(b, rel_tol=0, abs_tol=max(1e-12, 8 * math.ulp(magnitude)))

        if isinstance(boundary, PolylinePath):
            rows = [(float(x), float(y), 0.0, 0.0, float(bulge))
                    for x, y, bulge in boundary.vertices]
            points = []
            for index, row in enumerate(rows):
                if index + 1 == len(rows) and not boundary.is_closed:
                    points.append(wcs(row))
                else:
                    points.extend(wcs(p) for p in self._sample_bulge(
                        row, rows[(index + 1) % len(rows)]))
                if len(points) > MAX_CURVE_VERTICES:
                    raise ConversionError("Hatch boundary exceeds the vertex limit.")
            return [(points, bool(boundary.is_closed))]

        loops = []
        current: list[Any] = []
        for edge in boundary.edges:
            self.cancel.check()
            if isinstance(edge, LineEdge):
                local = [Vec3(edge.start), Vec3(edge.end)]
            elif isinstance(edge, ArcEdge):
                sweep = math.radians((edge.end_angle - edge.start_angle) % 360 or 360)
                local = self._arc_vertices(edge.center, edge.radius,
                                           math.radians(edge.start_angle), sweep)
                if not edge.ccw:
                    local.reverse()
            elif isinstance(edge, (EllipseEdge, SplineEdge)):
                if isinstance(edge, SplineEdge) and not edge.control_points:
                    if not edge.fit_points:
                        raise ConversionError("A hatch spline has no control or fit points.")
                    tangents = ((edge.start_tangent, edge.end_tangent)
                                if edge.start_tangent and edge.end_tangent else None)
                    tool = fit_points_to_cad_cv(edge.fit_points, tangents=tangents)
                else:
                    tool = edge.construction_tool()
                if isinstance(edge, EllipseEdge):
                    # EllipseEdge converts polar angles to parameters modulo one
                    # turn. Preserve an explicitly stored full revolution before
                    # that conversion collapses 30 -> 390 degrees to equal params.
                    start_angle, end_angle = float(edge.start_angle), float(edge.end_angle)
                    if not math.isfinite(start_angle) or not math.isfinite(end_angle):
                        raise ConversionError("A hatch ellipse has non-finite angles.")
                    angle_delta = end_angle - start_angle
                    roundoff = 8 * max(math.ulp(start_angle), math.ulp(end_angle), math.ulp(360.0))
                    if abs(abs(angle_delta) - 360.0) <= roundoff:
                        tool.end_param = tool.start_param + math.tau
                    elif abs(angle_delta) > 360.0 + roundoff:
                        raise ConversionError("A hatch ellipse interval exceeds one turn.")
                local = (self._ellipse_vertices(tool)[0] if isinstance(edge, EllipseEdge)
                         else self._collect_curve_vertices(tool.flattening(
                             self.job.curve_tolerance, segments=8)))
                if isinstance(edge, EllipseEdge) and not edge.ccw:
                    local.reverse()
            else:
                raise ConversionError(f"Unsupported hatch edge: {type(edge).__name__}.")
            points = [wcs(p) for p in local]
            if not points:
                raise ConversionError("A hatch edge has no usable vertices.")
            if not current:
                current = points
            elif coincident(current[-1], points[0]):
                current.extend(points[1:])
            elif coincident(current[-1], points[-1]):
                current.extend(reversed(points[:-1]))
            elif coincident(current[0], points[-1]):
                current = points[:-1] + current
            elif coincident(current[0], points[0]):
                current.reverse()
                current.extend(points[1:])
            elif coincident(current[0], current[-1]):
                loops.append((current, True))
                current = points
            else:
                # Match CAD's implicit connector between disconnected edge entries.
                # This is source-boundary reconstruction, not a geodetic shift.
                current.extend(points)
            if len(current) > MAX_CURVE_VERTICES:
                raise ConversionError("Hatch loop exceeds the vertex limit.")
        if current:
            loops.append((current, True))
        return loops

    def _horizontal_display_scale(self, anchor: Any) -> float:
        """Local area-equivalent XY scale; never use preserved metre Z for it."""
        matrix = self._local_matrix(anchor)
        ux = matrix.transform_direction(Vec3(1, 0, 0))
        uy = matrix.transform_direction(Vec3(0, 1, 0))
        determinant = ux.x * uy.y - ux.y * uy.x
        scale = math.sqrt(abs(determinant))
        if not math.isfinite(scale) or scale <= 0:
            raise ConversionError("No finite horizontal scale exists at this location.")
        return scale

    def _rescale_entity_linetype(self, entity: Any) -> None:
        """Scale model-space line-pattern distances, not shared paper-space tables."""
        if not self._scale_display_sizes or not entity.dxf.is_supported("ltscale"):
            return
        name = str(entity.dxf.get("linetype", "BYLAYER"))
        if name.upper() == "BYLAYER":
            layer = self.doc.layers.get(entity.dxf.layer)
            name = str(layer.dxf.linetype)
        if name.upper() in {"CONTINUOUS", "BYLAYER", "BYBLOCK"}:
            return
        anchor = self._entity_anchor(entity)
        if entity.dxftype() == "LINE" and (entity.dxf.end - entity.dxf.start).magnitude:
            tangent = (entity.dxf.end - entity.dxf.start).normalize()
            mapped = self._local_matrix(anchor).transform_direction(tangent)
            scale = mapped.magnitude
        else:
            scale = self._horizontal_display_scale(anchor)
        value = float(entity.dxf.ltscale) * scale
        if not math.isfinite(value) or value <= 0:
            raise ConversionError("The rescaled linetype distance is invalid.")
        entity.dxf.ltscale = value
        self.result.add_issue(
            "information", "linetype_units_rescaled",
            f"Linetype distances use a local horizontal scale of {scale:.12g}. "
            "The shared linetype table is unchanged; this is a local appearance approximation.",
            entity,
        )

    def _entity_anchor(self, entity: Any) -> Any:
        kind = entity.dxftype()
        if kind in {"TEXT", "ATTRIB", "ATTDEF"}:
            _align, point, _second = entity.get_placement()
            return entity.ocs().to_wcs(point)
        if kind in {"ARC", "CIRCLE"}:
            angle = math.radians(float(entity.dxf.start_angle)) if kind == "ARC" else 0.0
            center = Vec3(entity.dxf.center)
            point = center + Vec3(float(entity.dxf.radius) * math.cos(angle),
                                  float(entity.dxf.radius) * math.sin(angle), 0.0)
            return entity.ocs().to_wcs(point)
        if kind == "ELLIPSE":
            return next(entity.vertices([entity.dxf.start_param]))
        if kind == "LEADER" and entity.vertices:
            return Vec3(entity.vertices[0])
        if kind == "LWPOLYLINE" and len(entity):
            return next(entity.vertices_in_wcs())
        if kind == "POLYLINE" and entity.vertices:
            return next(entity.points_in_wcs())
        if kind in {"HATCH", "MPOLYGON"}:
            for path in paths_from_hatch(entity):
                if len(path):
                    return path.start
        for name in ("insert", "location", "start", "center", "vtx0"):
            if entity.dxf.hasattr(name):
                with contextlib.suppress(Exception):
                    point = Vec3(entity.dxf.get(name))
                    if kind in {"TEXT", "ATTRIB", "ATTDEF", "ARC", "CIRCLE", "SOLID", "TRACE"}:
                        return entity.ocs().to_wcs(point)
                    return point
        with contextlib.suppress(Exception):
            extents = ezdxf_bbox.extents([entity], fast=True)
            if extents.has_data:
                return extents.center
        raise ConversionError(
            f"No usable WCS anchor is exposed by {kind}; an artificial (0, 0, 0) "
            "must not be interpreted as a surveyed location."
        )

    def _exact_points(self, entity: Any) -> None:
        entity_type = entity.dxftype()
        fields = {
            "LINE": ("start", "end"),
            "POINT": ("location",),
            "3DFACE": ("vtx0", "vtx1", "vtx2", "vtx3"),
            "SOLID": ("vtx0", "vtx1", "vtx2", "vtx3"),
            "TRACE": ("vtx0", "vtx1", "vtx2", "vtx3"),
        }[entity_type]
        thickness = float(entity.dxf.get("thickness", 0)) if entity.dxf.is_supported("thickness") else 0.0
        thickness_vector = None
        if thickness:
            anchor = self._entity_anchor(entity)
            normal = entity.ocs().uz
            thickness_vector = self.transform_point(anchor + normal * thickness) - self.transform_point(anchor)
        if entity_type == "LINE":
            points = self._transform_path((entity.dxf.start, entity.dxf.end), False)
            if len(points) > 2:
                self._replace_by_polyline(entity, points, False, transformed=True)
                self.result.approximated["LINE"] += 1
                return
        if entity_type in {"SOLID", "TRACE"}:
            points = [self.transform_point(entity.ocs().to_wcs(entity.dxf.get(name)))
                      for name in fields]
            for name, point in zip(fields, points, strict=True):
                entity.dxf.set(name, point)
            entity.dxf.extrusion = Vec3(0.0, 0.0, 1.0)
        else:
            transformed = {
                name: self.transform_point(entity.dxf.get(name))
                for name in fields
                if entity.dxf.hasattr(name)
            }
            for name, point in transformed.items():
                entity.dxf.set(name, point)
        if thickness_vector is not None:
            length = thickness_vector.magnitude
            entity.dxf.thickness = math.copysign(length, thickness)
            entity.dxf.extrusion = thickness_vector / entity.dxf.thickness if length else Vec3(0, 0, 1)
            if entity_type in {"SOLID", "TRACE"}:
                ocs = entity.ocs()
                for name, point in zip(fields, points, strict=True):
                    entity.dxf.set(name, ocs.from_wcs(point))
            self.result.add_issue("information", "thickness_local",
                                  "Extrusion thickness was mapped at the first anchor; it is a local representation.", entity)
        self.result.transformed[entity_type] += 1

    def _add_output(self, layout: Any, entity: Any) -> None:
        """Track even a partially bound replacement before it reaches a layout."""
        self._active_outputs.append(entity)
        layout.add_entity(entity)
        if self._active_origin is not None:
            self._output_origins[str(entity.dxf.handle)] = self._active_origin

    def _new_polyline_output(
        self,
        layout: Any,
        points: Sequence[Any],
        attributes: dict[str, Any],
        closed: bool,
        *,
        lightweight: bool,
    ) -> Any:
        from ezdxf.entities import factory

        if lightweight:
            replacement = factory.new("LWPOLYLINE", dxfattribs=attributes)
            replacement.set_points([(point.x, point.y) for point in points])
        else:
            replacement = factory.new("POLYLINE", dxfattribs={**attributes, "flags": 8})
            replacement.append_vertices(points)
            replacement.new_seqend()
        replacement.close(closed)
        self._add_output(layout, replacement)
        return replacement

    def _discard_entity(self, entity: Any) -> None:
        """Destroy owned data immediately; compact layout lists once per pass."""
        if not entity.is_alive:
            return
        layout = entity.get_layout()
        if self._defer_deletion and layout is not None:
            self._deferred_layouts[id(layout)] = layout
            self.doc.entitydb.delete_entity(entity)
        elif layout is not None:
            layout.delete_entity(entity)
        elif entity.dxf.handle in self.doc.entitydb:
            self.doc.entitydb.delete_entity(entity)
        else:
            entity.destroy()

    def _purge_discarded_entities(self) -> None:
        for layout in self._deferred_layouts.values():
            layout.purge()
        self._deferred_layouts.clear()

    def _record_omission(
        self, entity_type: str, handle: str, layout_name: str, reason: str
    ) -> None:
        source_type, source_handle, source_layout = self._active_origin or (
            entity_type,
            handle,
            layout_name,
        )
        self.result.omitted[entity_type] += 1
        self.result.issues.append(
            EntityIssue(
                severity="warning",
                code="entity_omitted",
                message=(
                    f"Omitted from the converted drawing: {reason.rstrip('. ')}. "
                    "The source drawing is unchanged. This object comes from "
                    f"{source_type} handle {source_handle} in {source_layout}."
                ),
                layout=layout_name,
                entity_type=entity_type,
                handle=handle,
                source_handle=source_handle,
                source_entity_type=source_type,
                source_layout=source_layout,
            )
        )
        self._omission_log_count += 1
        if self._omission_log_count <= OMISSION_LOG_LIMIT:
            self.log(f"Omitted {entity_type} {handle} in {layout_name}: {reason}")
        elif self._omission_log_count == OMISSION_LOG_LIMIT + 1:
            self.log("Further object omissions are recorded in the JSON report; "
                     "per-object logging is suppressed to keep large jobs responsive.")

    def _reject_entity(self, entity: Any, code: str, reason: str) -> None:
        entity_type = entity.dxftype()
        handle = str(entity.dxf.get("handle", "") or "")
        layout_name = getattr(entity.get_layout(), "name", "<unknown>")
        self.result.unresolved[entity_type] += 1
        if self.job.strict_unresolved:
            self.result.add_issue(
                "error",
                code,
                f"Original object retained without reprojection. {reason}",
                entity,
            )
            self.log(f"Unresolved {entity_type} {handle}: {reason}")
        else:
            self._discard_entity(entity)
            self._record_omission(entity_type, handle, layout_name, reason)

    def _replace_by_polyline(
        self, entity: Any, vertices: Iterable[Any], closed: bool, *, transformed: bool = False
    ) -> Any:
        layout = entity.get_layout()
        if layout is None:
            raise ConversionError("Entity is not assigned to a layout.")
        points = list(vertices) if transformed else self._transform_path(vertices, closed)
        if (
            closed and entity.dxftype() in {"ARC", "CIRCLE", "ELLIPSE", "SPLINE", "HELIX"}
            and len(points) > 2
            and points[0].isclose(points[-1], rel_tol=0.0, abs_tol=1e-12)
        ):
            points.pop()
        if len(points) < 2:
            raise ConversionError(
                f"Faceting {entity.dxftype()} produced {len(points)} vertices; "
                "at least two are required to represent this curve."
            )
        attributes = _graphic_attributes(entity)
        same_z = (
            max(point.z for point in points) - min(point.z for point in points) <= 1e-10
        )
        if same_z and not self.target_crs.is_geocentric:
            attributes["elevation"] = float(points[0].z)
        thickness = float(entity.dxf.get("thickness", 0)) if entity.dxf.is_supported("thickness") else 0
        if thickness:
            anchor = self._entity_anchor(entity)
            normal = entity.ocs().uz
            offset = self.transform_point(anchor + normal * thickness) - self.transform_point(anchor)
            if not same_z or self.target_crs.is_geocentric or math.hypot(offset.x, offset.y) > 1e-12:
                raise ConversionError("This faceted curve's non-horizontal extrusion cannot be represented without losing thickness.")
            attributes["thickness"] = offset.z
        replacement = self._new_polyline_output(
            layout,
            points,
            attributes,
            closed,
            lightweight=same_z and not self.target_crs.is_geocentric,
        )
        _copy_xdata(entity, replacement)
        self._discard_entity(entity)
        return replacement

    def _sample_bulge(
        self, start: tuple[float, ...], end: tuple[float, ...]
    ) -> Iterator[tuple[float, float, float, float, float]]:
        """Yield segment starts in source OCS, including interpolated widths.

        The following segment supplies the exact endpoint. Local chord-based
        arithmetic avoids relative-coordinate tests and large-centre subtraction.
        Circular sagitta controls the source-space approximation directly.
        """
        x, y, start_width, end_width, bulge = start
        dx, dy = end[0] - x, end[1] - y
        chord = math.hypot(dx, dy)
        if bulge == 0.0 or chord == 0.0:
            yield x, y, start_width, end_width, 0.0
            return
        magnitude = abs(bulge)
        sagitta = chord * (magnitude / 2.0)
        # An extremely shallow arc needs no intermediate point when its entire
        # deviation from the chord is below the requested tolerance.
        if magnitude < 1e-12 and sagitta <= self.job.curve_tolerance:
            yield x, y, start_width, end_width, 0.0
            return
        radius = (chord / 4.0) * (magnitude + 1.0 / magnitude)
        center_offset = (chord / 4.0) * (1.0 / bulge - bulge)
        sweep = 4.0 * math.atan(bulge)
        if not all(math.isfinite(v) for v in (radius, center_offset, sagitta)):
            raise ConversionError("A polyline bulge defines a non-finite arc.")
        if radius <= 0.0:
            raise ConversionError("A polyline bulge has no representable radius.")
        ratio = min(1.0, (self.job.curve_tolerance / radius) / 2.0)
        step = 4.0 * math.asin(math.sqrt(ratio))
        if step <= 0.0 or abs(sweep) > step * 1_000_000:
            raise ConversionError(
                "A polyline arc requires more than 1,000,000 segments at the "
                "selected tolerance. Check the source units and curve tolerance."
            )
        count = max(8, math.ceil(abs(sweep) / step))
        ux, uy = dx / chord, dy / chord
        for index in range(count):
            if index % 256 == 0:
                self.cancel.check()
            t = index / count
            if index == 0:
                px, py = x, y
            else:
                angle = sweep * t
                half_sine_squared = math.sin(angle / 2.0) ** 2
                along = chord * half_sine_squared + center_offset * math.sin(angle)
                across = 2.0 * center_offset * half_sine_squared - (
                    chord / 2.0
                ) * math.sin(angle)
                px = x + ux * along - uy * across
                py = y + uy * along + ux * across
            yield (
                px,
                py,
                start_width + (end_width - start_width) * t,
                start_width + (end_width - start_width) * ((index + 1) / count),
                0.0,
            )

    def _try_linear_lwpolyline(self, entity: Any) -> bool:
        """Batch straight, unweighted WCS polylines; fall back before any mutation.

        Every endpoint and every 1/4, 1/2 and 3/4 probe uses the mandatory full
        coordinate chain. Edges needing subdivision, non-WCS planes, widths,
        bulges, thickness and 3D CRS operations retain the general handler.
        No spatial rounding, vertex decimation or reduced tolerance is applied.
        """
        if (entity.dxftype() != "LWPOLYLINE" or len(entity) < 16 or self.use_3d
                or tuple(entity.dxf.extrusion) != (0.0, 0.0, 1.0)
                or entity.dxf.thickness or entity.dxf.const_width):
            return False
        rows = _lwpolyline_rows(entity)
        if np.any(rows[:, 2:]):
            return False
        elevation = float(entity.dxf.elevation)
        if not np.isfinite(rows).all() or not math.isfinite(elevation):
            raise ConversionError("Polyline contains non-finite coordinates or attributes.")
        n = len(rows)
        if n > MAX_CURVE_VERTICES:
            raise ConversionError("The polyline exceeds the output vertex limit.")
        closed = bool(entity.is_closed)
        edge_count = n if closed else n - 1
        output = np.empty((n, 2), dtype=np.float64)
        for begin in range(0, edge_count, 512):
            self.cancel.check()
            self._entity_progress(.85 * begin / max(1, edge_count))
            indexes = np.arange(begin, min(begin + 512, edge_count))
            a, b = rows[indexes, :2], rows[(indexes + 1) % n, :2]
            probes = np.empty((len(indexes), 5, 2), dtype=np.float64)
            probes[:, 0, :], probes[:, 1, :] = a, b
            probes[:, 2:, :] = a[:, None, :] + (b - a)[:, None, :] * np.array([.25, .5, .75])[None, :, None]
            flat = probes.reshape(-1, 2)
            if len(self._roundtrip_samples) < 32:
                for xy in flat[:32 - len(self._roundtrip_samples)]:
                    self.transform_point((xy[0], xy[1], elevation))
            try:
                mapped = self.transformer.transform_many(flat).reshape(-1, 5, 2)
            except CoordinateTransformationError:
                # Re-enter normal per-entity code to retain exact coordinate-role
                # diagnostics and the existing skip/strict rollback policy.
                return False
            self._batch_calls += 1
            self._point_transform_count += len(flat)
            factors = np.ones_like(mapped[:, 2:, :])
            if self._target_geographic:
                _, radius, e2 = self._metric_ellipsoids[0]
                phi = np.deg2rad(mapped[:, 2:, 1])
                d = 1 - e2 * np.sin(phi) ** 2
                factors[:, :, 0] = np.maximum(1e-9, math.pi / 180 * radius * np.abs(np.cos(phi)) / np.sqrt(d))
                factors[:, :, 1] = math.pi / 180 * radius * (1 - e2) / d ** 1.5
                if np.any(np.abs(mapped[:, 1, 0] - mapped[:, 0, 0]) > 180):
                    return False
            v = (mapped[:, 1, :] - mapped[:, 0, :])[:, None, :] * factors
            w = (mapped[:, 2:, :] - mapped[:, 0, :][:, None, :]) * factors
            denom = np.sum(v * v, axis=2)
            t = np.zeros_like(denom)
            np.divide(np.sum(w * v, axis=2), denom, out=t, where=denom != 0)
            error = np.sqrt(np.sum((w - v * np.clip(t, 0, 1)[:, :, None]) ** 2, axis=2))
            lengths = b - a
            if self.source_crs.is_geographic:
                _, radius, e2 = self._metric_ellipsoids[1]
                phi = np.deg2rad((a[:, 1] + b[:, 1]) * .5)
                d = 1 - e2 * np.sin(phi) ** 2
                lengths = lengths * np.column_stack((
                    np.maximum(1e-9, math.pi / 180 * radius * np.abs(np.cos(phi)) / np.sqrt(d)),
                    math.pi / 180 * radius * (1 - e2) / d ** 1.5))
            if (not np.isfinite(error).all()
                    or np.any(error > self.job.reprojection_tolerance_m - 1e-10)
                    or np.any(np.sum(lengths * lengths, axis=1) > (1000 - 1e-9) ** 2)):
                return False
            output[indexes, :] = mapped[:, 0, :]
            if not closed and indexes[-1] == n - 2:
                output[-1, :] = mapped[-1, 1, :]
        # Update via the entity API only after all edges and positions have passed.
        entity.set_points(output, format="xy")
        entity.dxf.elevation = elevation if self.job.preserve_z else 0.0
        entity.close(closed)
        self.result.transformed["LWPOLYLINE"] += 1
        self._linear_polyline_batches += 1
        return True

    def _polyline_2d(
        self, entity: Any, *, source_vertices: list[Any] | None = None
    ) -> Any:
        """Stage all coordinates before changing a lightweight/ordinary 2D polyline."""
        if source_vertices is None and self._try_linear_lwpolyline(entity):
            return entity
        lightweight = entity.dxftype() == "LWPOLYLINE"
        entity_type = entity.dxftype()
        closed = bool(entity.is_closed)
        if lightweight:
            records = [
                tuple(float(v) for v in row) for row in entity.get_points("xyseb")
            ]
            elevation = float(entity.dxf.elevation)
            constant_width = float(entity.dxf.const_width)
        else:
            originals = (
                list(entity.vertices) if source_vertices is None else source_vertices
            )
            records = [
                (
                    float(vertex.dxf.location.x),
                    float(vertex.dxf.location.y),
                    float(
                        vertex.dxf.get("start_width", entity.dxf.default_start_width)
                    ),
                    float(vertex.dxf.get("end_width", entity.dxf.default_end_width)),
                    float(vertex.dxf.bulge),
                )
                for vertex in originals
            ]
            fallback = originals[0].dxf.location if records else Vec3()
            elevation = float(Vec3(entity.dxf.get("elevation", fallback)).z)
            constant_width = 0.0
        thickness = float(entity.dxf.thickness)
        if not all(
            math.isfinite(value) for value in (elevation, constant_width, thickness)
        ) or not all(math.isfinite(value) for record in records for value in record):
            raise ConversionError(
                "A polyline contains non-finite coordinates or attributes."
            )
        if not records:
            # ezdxf does not serialize a zero-vertex LWPOLYLINE. Remove it
            # explicitly and report that fact before output counts are checked.
            # There is no geometric point to move or to replace with a POINT.
            if lightweight:
                layout = entity.get_layout()
                if layout is None:
                    raise ConversionError("Empty polyline is not assigned to a layout.")
                self.result.add_issue(
                    "warning",
                    "empty_polyline_omitted",
                    "The zero-vertex LWPOLYLINE has no geometry and cannot be "
                    "serialized by the DXF writer; it was omitted without inventing vertices.",
                    entity,
                )
                self._discard_entity(entity)
                self.result.transformed["LWPOLYLINE_EMPTY_OMITTED"] += 1
                return
            self.result.transformed[f"{entity_type}_EMPTY_PRESERVED"] += 1
            self.result.add_issue(
                "information",
                "empty_polyline_preserved",
                "The empty polyline was retained; it has no vertices to reproject.",
                entity,
            )
            return entity
        sampled: list[tuple[float, float, float, float, float]] = []
        source_offsets: list[int] = []
        curved = False
        zero_length_bulges = 0
        ocs = entity.ocs()
        straight_records = not any(r[4] for r in records)
        for index, record in enumerate(records):
            if straight_records and index % 256 == 0 and len(records) >= 16:
                batch_records = records[index:index + 257]
                if closed and index + 256 >= len(records):
                    batch_records = batch_records + records[:1]
                self._prime_edges([ocs.to_wcs((r[0], r[1], elevation)) for r in batch_records])
            if index % 128 == 0:
                self._entity_progress(0.65 * index / len(records))
            self.cancel.check()
            source_offsets.append(len(sampled))
            if not closed and index == len(records) - 1:
                sampled.append(record)
                break
            following = records[(index + 1) % len(records)]
            if record[4] != 0.0:
                if record[:2] == following[:2]:
                    zero_length_bulges += 1
                else:
                    curved = True
            arc_records = list(self._sample_bulge(record, following))
            for j, arc_record in enumerate(arc_records):
                if j % 256 == 0 and len(arc_records) > 256:
                    self._entity_progress(0.65 * (index + j / len(arc_records)) / len(records))
                next_record = arc_records[j + 1] if j + 1 < len(arc_records) else following
                a = ocs.to_wcs((arc_record[0], arc_record[1], elevation))
                b = ocs.to_wcs((next_record[0], next_record[1], elevation))
                edge = self._edge_samples(a, b)
                curved |= len(edge) > 2
                for (t0, _, _), (t1, _, _) in zip(edge, edge[1:]):
                    sampled.append((
                        arc_record[0] + (next_record[0] - arc_record[0]) * t0,
                        arc_record[1] + (next_record[1] - arc_record[1]) * t0,
                        arc_record[2] + (arc_record[3] - arc_record[2]) * t0,
                        arc_record[2] + (arc_record[3] - arc_record[2]) * t1,
                        0.0,
                    ))
                if len(sampled) > MAX_CURVE_VERTICES:
                    raise ConversionError("The polyline exceeds the output vertex limit.")
        if not all(math.isfinite(value) for record in sampled for value in record):
            raise ConversionError(
                "Polyline faceting produced non-finite coordinates or widths."
            )
        self._entity_progress(0.68)
        points = self.transform_points(ocs.to_wcs((r[0], r[1], elevation)) for r in sampled)
        horizontal = (
            not self.target_crs.is_geocentric
            and max(p.z for p in points) - min(p.z for p in points) <= 1e-10
        )
        has_width = constant_width != 0.0 or any(
            r[2] != 0.0 or r[3] != 0.0 for r in sampled
        )
        if not horizontal and (has_width or thickness != 0.0):
            raise ConversionError(
                "The transformed 2D polyline is not horizontal and carries width "
                "or thickness. A plain 3D polyline would lose that geometry."
            )
        output_thickness = thickness
        if horizontal and thickness != 0.0:
            anchor = ocs.to_wcs((sampled[0][0], sampled[0][1], elevation))
            tip = self.transform_point(anchor + ocs.uz * thickness)
            offset = tip - points[0]
            if abs(offset.x) > 1e-10 or abs(offset.y) > 1e-10:
                raise ConversionError(
                    "The transformed polyline thickness is not perpendicular to its "
                    "horizontal plane and cannot be preserved by a 2D polyline."
                )
            output_thickness = offset.z
        output = []
        width_rescaled = bool(has_width and self._scale_display_sizes)
        for index, (point, record) in enumerate(zip(points, sampled, strict=True)):
            if index % 128 == 0:
                self._entity_progress(0.7 + 0.25 * index / len(sampled))
            sw, ew = (constant_width, constant_width) if constant_width else (record[2], record[3])
            if width_rescaled:
                next_index = (index + 1) % len(sampled) if closed else min(index + 1, len(sampled) - 1)
                following = sampled[next_index]
                tangent = Vec3(following[0] - record[0], following[1] - record[1], 0)
                if not closed and index == len(sampled) - 1 and index:
                    previous = sampled[index - 1]
                    tangent = Vec3(record[0] - previous[0], record[1] - previous[1], 0)
                start_anchor = ocs.to_wcs((record[0], record[1], elevation))
                end_anchor = ocs.to_wcs((following[0], following[1], elevation))
                sw *= self._perpendicular_width_scale(start_anchor, tangent, ocs)
                ew *= self._perpendicular_width_scale(end_anchor, tangent, ocs)
            output.append((point.x, point.y, sw, ew, 0.0))
        # Commit only after every sample and coordinate has passed validation.
        if horizontal and lightweight:
            entity.set_points(output, format="xyseb")
            if entity.dxf.hasattr("const_width"):
                entity.dxf.const_width = 0.0 if width_rescaled else constant_width
            entity.dxf.elevation = points[0].z
            entity.dxf.extrusion = Vec3(0.0, 0.0, 1.0)
            if entity.dxf.hasattr("thickness"):
                entity.dxf.thickness = output_thickness
            entity.close(closed)
        elif horizontal:
            all_originals = list(entity.vertices)
            original_slots = set(source_offsets)
            if len(output) != len(originals):
                entity.append_vertices(
                    (row[0], row[1], 0.0)
                    for index, row in enumerate(output)
                    if index not in original_slots
                )
            extra_vertices = iter(entity.vertices[len(all_originals) :])
            original_vertices = iter(originals)
            entity.vertices[:] = [
                next(original_vertices)
                if index in original_slots
                else next(extra_vertices)
                for index in range(len(output))
            ]
            selected_ids = {id(vertex) for vertex in originals}
            for vertex in all_originals:
                if id(vertex) not in selected_ids:
                    # Auxiliary fit records have already been captured by the
                    # caller. They must not become visible connecting segments.
                    self.doc.entitydb.delete_entity(vertex)
            for vertex, row in zip(entity.vertices, output, strict=True):
                vertex.dxf.location = Vec3(row[0], row[1], 0.0)
                vertex.dxf.start_width = row[2]
                vertex.dxf.end_width = row[3]
                vertex.dxf.bulge = row[4]
            if width_rescaled:
                entity.dxf.default_start_width = 0.0
                entity.dxf.default_end_width = 0.0
            entity.dxf.elevation = Vec3(0.0, 0.0, points[0].z)
            entity.dxf.extrusion = Vec3(0.0, 0.0, 1.0)
            if entity.dxf.hasattr("thickness"):
                entity.dxf.thickness = output_thickness
        else:
            layout = entity.get_layout()
            if layout is None:
                raise ConversionError("Polyline is not assigned to a layout.")
            attributes = _graphic_attributes(entity)
            replacement = self._new_polyline_output(
                layout,
                points,
                attributes,
                closed,
                lightweight=False,
            )
            _copy_xdata(entity, replacement)
            # Record issues with the original handle before deleting the source.
            self.result.add_issue(
                "information",
                "polyline_representation_changed",
                f"The polyline was represented as {replacement.dxftype()} with its original closed flag.",
                entity,
            )
            self._discard_entity(entity)
            entity = replacement
        counter = self.result.approximated if curved else self.result.transformed
        counter[entity_type] += 1
        if zero_length_bulges:
            self.result.add_issue(
                "warning",
                "zero_length_bulge_cleared",
                f"Retained coincident vertices and cleared {zero_length_bulges} bulge(s) "
                "on zero-length segments; those segments define no finite arc.",
                entity,
            )
        if has_width or thickness != 0.0:
            self.result.add_issue(
                "information", "polyline_width_local_rescaled" if width_rescaled else "polyline_width_local",
                ("Widths use separate local perpendicular scales at both ends of each segment; "
                 "constant widths are expanded into segment widths. This is a first-order "
                 "representation, not an exact nonlinear transformation of the full width envelope. "
                 if width_rescaled else "Stored widths were retained. ") +
                "Thickness is mapped at the first vertex; closure and coincident vertices are retained.",
                entity,
            )
        return entity

    def _fitted_polyline(self, entity: Any) -> None:
        """Materialize stored fitted arcs before nonlinear reprojection.

        A general CRS Jacobian is not a similarity matrix, so applying it to
        circular bulges with Polyline.transform() is not representable. Fitted
        display vertices and spline-frame control vertices are distinct data.
        """
        if not entity.vertices:
            self._polyline_2d(entity)
            return
        if not entity.has_arc:
            self._local_affine(entity, "fitted_polyline_local_affine")
            return

        from ezdxf.lldxf.tagwriter import TagCollector

        flags = int(entity.dxf.flags)
        vertices = list(entity.vertices)
        if any(int(vertex.dxf.flags) & 24 == 24 for vertex in vertices):
            raise ConversionError(
                "A fitted polyline vertex is marked as both a displayed spline "
                "vertex and a spline-frame control point. Its role is ambiguous."
            )
        if flags & 4:
            display = [vertex for vertex in vertices if int(vertex.dxf.flags) & 8]
            if not display:
                if any(int(vertex.dxf.flags) & 16 for vertex in vertices):
                    raise ConversionError(
                        "The spline-fitted polyline has control points but no stored "
                        "display vertices. Its curve cannot be reconstructed safely."
                    )
                # Some writers retain the header fit bit on an ordinary arc
                # chain without emitting any spline-specific vertex flags.
                display = vertices
        else:
            # Curve fitting inserts extra vertices (bit 1) into the same arc
            # chain as the original vertices; both are required for display.
            display = [vertex for vertex in vertices if not int(vertex.dxf.flags) & 16]
        if not display:
            raise ConversionError("The fitted polyline has no stored display vertices.")
        selected_ids = {id(vertex) for vertex in display}
        archive = {
            "source_handle": str(entity.dxf.handle),
            "source_epsg": self.job.source_epsg,
            "source_dxf_version": self.doc.dxfversion,
            "source_flags": flags,
            "source_smooth_type": int(entity.dxf.smooth_type),
            "display_vertex_handles": [str(vertex.dxf.handle) for vertex in display],
            "auxiliary_vertex_handles": [
                str(vertex.dxf.handle)
                for vertex in vertices
                if id(vertex) not in selected_ids
            ],
            "source_dxf": "".join(
                tag.dxfstr()
                for tag in TagCollector.dxftags(entity, dxfversion=self.doc.dxfversion)
            ),
        }
        target = self._polyline_2d(entity, source_vertices=display)
        target.dxf.flags = int(target.dxf.flags) & ~6
        target.dxf.smooth_type = 0
        for vertex in target.vertices:
            vertex.dxf.flags = int(vertex.dxf.flags) & ~27
            vertex.dxf.discard("tangent")
            vertex.dxf.bulge = 0.0
        archive["output_handle"] = str(target.dxf.handle)
        self.result.fitted_polyline_sources.append(archive)
        self.result.add_issue(
            "warning",
            "fitted_polyline_faceted",
            "The stored fitted display path was sampled and reprojected as an "
            "ordinary polyline. Fit/tangent editing semantics were removed; the "
            "original POLYLINE/VERTEX/SEQEND tags, including auxiliary control "
            "vertices, are archived in fitted_polyline_sources in the JSON report.",
            target,
        )

    def _polyline_or_curve(self, entity: Any) -> None:
        entity_type = entity.dxftype()
        if entity_type == "LWPOLYLINE":
            self._polyline_2d(entity)
            return
        if entity_type == "POLYLINE":
            mode = entity.get_mode()
            if mode in {"AcDb3dPolyline", "AcDbPolygonMesh", "AcDbPolyFaceMesh"}:
                if mode == "AcDb3dPolyline":
                    source_points = [v.dxf.location for v in entity.vertices]
                    points = self._transform_path(source_points, bool(entity.is_closed))
                    if len(points) != len(source_points):
                        self._replace_by_polyline(entity, points, bool(entity.is_closed), transformed=True)
                        self.result.approximated[entity_type] += 1
                        return
                vertices = [
                    vertex
                    for vertex in entity.vertices
                    if not (mode == "AcDbPolyFaceMesh" and vertex.is_face_record)
                ]
                points = [
                    self.transform_point(vertex.dxf.location) for vertex in vertices
                ]
                for vertex, point in zip(vertices, points, strict=True):
                    vertex.dxf.location = point
                self.result.transformed[entity_type] += 1
                return
            if int(entity.dxf.flags) & 6:
                self._fitted_polyline(entity)
            else:
                self._polyline_2d(entity)
            return
        vertices, is_closed = self._source_curve_vertices(entity)
        self._replace_by_polyline(entity, vertices, is_closed)
        self.result.approximated[entity_type] += 1

    def _hatch(self, entity: Any) -> None:
        """Map each original boundary separately, retaining its path flags and holes."""
        ocs = entity.ocs()
        elevation = float(entity.dxf.elevation.z)
        loops: list[tuple[list[Any], int, bool]] = []
        source_anchor = None
        split_boundaries = 0
        source_bounds = [math.inf, math.inf, -math.inf, -math.inf]
        for boundary in entity.paths:
            self.cancel.check()
            parts = self._hatch_source_loops(boundary, ocs, elevation)
            split_boundaries += max(0, len(parts) - 1)
            for source_points, closed in parts:
                # Check duplication in SOURCE coordinates with no relative tolerance.
                # Default Vec3.isclose() on longitude/latitude can erase short edges.
                if (len(source_points) > 1 and source_points[0].isclose(
                        source_points[-1], rel_tol=0.0, abs_tol=1e-12)):
                    source_points.pop()
                    closed = True
                if len(source_points) < 3:
                    raise ConversionError("Hatch boundary produced fewer than three vertices.")
                if source_anchor is None:
                    source_anchor = source_points[0]
                for p in source_points:
                    source_bounds[0] = min(source_bounds[0], p.x)
                    source_bounds[1] = min(source_bounds[1], p.y)
                    source_bounds[2] = max(source_bounds[2], p.x)
                    source_bounds[3] = max(source_bounds[3], p.y)
                points = self._transform_path(source_points, closed)
                loops.append((points, int(boundary.path_type_flags), closed))
        if not loops:
            raise ConversionError("Hatch has no usable boundary vertices.")
        zs = [p.z for points, _flags, _closed in loops for p in points]
        # A CAD HATCH must be planar. Do not silently flatten sloping/nonplanar
        # output, particularly when XY becomes degrees but Z remains metres.
        horizontal = (not self.target_crs.is_geocentric
                      and max(zs) - min(zs) <= 1e-10)
        if not horizontal:
            if self.job.strict_unresolved:
                raise ConversionError(
                    "The reprojected hatch is not horizontal. A boundary-only "
                    "representation would lose the fill; strict mode prevents it."
                )
            layout = entity.get_layout()
            if layout is None:
                raise ConversionError("Hatch is not assigned to a layout.")
            from ezdxf.lldxf.tagwriter import TagCollector
            # Keep the original fill/boundary definition as recovery provenance.
            archive = {
                "source_type": entity.dxftype(),
                "source_handle": str(entity.dxf.handle),
                "source_epsg": self.job.source_epsg,
                "source_dxf": "".join(tag.dxfstr() for tag in
                    TagCollector.dxftags(entity, dxfversion=self.doc.dxfversion)),
            }
            replacements = []
            for points, _flags, closed in loops:
                replacement = self._new_polyline_output(
                    layout, points, _graphic_attributes(entity), closed,
                    lightweight=False,
                )
                _copy_xdata(entity, replacement)
                replacements.append(str(replacement.dxf.handle))
            archive["output_handles"] = replacements
            self.result.hatch_boundary_sources.append(archive)
            self.result.add_issue(
                "warning", "hatch_boundary_only",
                "The transformed hatch cannot be stored as a horizontal HATCH. "
                "Its sampled 3D boundary loops and elevations were preserved as "
                "polylines; the fill/pattern is not retained. Original hatch tags "
                "are archived in hatch_boundary_sources in the JSON report.", entity,
            )
            self.result.approximated[f"{entity.dxftype()}_BOUNDARY_ONLY"] += 1
            self._discard_entity(entity)
            return

        # Seed points are positional data too; keeping metre seeds in a
        # longitude/latitude hatch leaves internally inconsistent geometry.
        seeds = []
        removed_seeds = []
        for seed in entity.seeds:
            point = ocs.to_wcs((seed[0], seed[1], elevation))
            previous_role = self._coordinate_role
            self._coordinate_role = "optional hatch seed (not a boundary vertex)"
            try:
                seeds.append(self.transform_point(point))
            except CoordinateTransformationError as exc:
                outside = (not all(math.isfinite(v) for v in point) or
                           not (source_bounds[0] <= point.x <= source_bounds[2]
                                and source_bounds[1] <= point.y <= source_bounds[3]))
                if not outside:
                    raise
                # No extrapolation or replacement datum: only an orphaned optional
                # construction seed is removed, after every boundary has passed.
                encode = lambda v: float(v) if math.isfinite(float(v)) else repr(float(v))
                removed_seeds.append({"source_ocs": [encode(seed[0]), encode(seed[1])],
                                      "source_wcs": [encode(v) for v in point], "reason": str(exc)})
            finally:
                self._coordinate_role = previous_role
        if removed_seeds:
            self.result.auxiliary_coordinate_repairs.append({
                "entity_type": entity.dxftype(), "handle": str(entity.dxf.handle),
                "source_epsg": self.job.source_epsg, "removed_hatch_seeds": removed_seeds,
                "boundary_geometry_preserved": True,
            })
            self.result.add_issue("information", "invalid_hatch_seed_removed",
                f"Removed {len(removed_seeds)} untransformable optional hatch seed(s) "
                "outside the boundary envelope. All boundary geometry passed the "
                "mandatory operation. Original seeds are archived in auxiliary_coordinate_repairs.", entity)
        pattern_definition = None
        pattern_scale = 1.0
        if self._scale_display_sizes and entity.has_pattern_fill and entity.pattern:
            matrix = self._local_matrix(source_anchor)
            pattern_scale = self._horizontal_display_scale(source_anchor)
            pattern_definition = []
            for line in entity.pattern.lines:
                theta = math.radians(line.angle)
                direction = matrix.transform_direction(ocs.to_wcs(
                    Vec3(math.cos(theta), math.sin(theta), 0)
                ))
                length_scale = math.hypot(direction.x, direction.y)
                if not math.isfinite(length_scale) or length_scale <= 0:
                    raise ConversionError("A hatch pattern line has an invalid local scale.")
                base = matrix.transform(ocs.to_wcs(
                    (line.base_point.x, line.base_point.y, elevation)
                ))
                offset = matrix.transform_direction(ocs.to_wcs(
                    (line.offset.x, line.offset.y, 0)
                ))
                pattern_definition.append((
                    math.degrees(math.atan2(direction.y, direction.x)),
                    (base.x, base.y), (offset.x, offset.y),
                    [item * length_scale for item in line.dash_length_items],
                ))
        # Commit after validating all boundary/seed coordinates and pattern data.
        if hasattr(entity, "remove_association"):
            entity.remove_association()
        entity.paths.clear()
        for points, flags, closed in loops:
            entity.paths.add_polyline_path(
                [(p.x, p.y, 0.0) for p in points], is_closed=closed, flags=flags
            )
        entity.dxf.elevation = Vec3(0, 0, zs[0])
        entity.dxf.extrusion = Vec3(0, 0, 1)
        entity.seeds = [(p.x, p.y) for p in seeds]
        entity.dxf.n_seed_points = len(seeds)
        if pattern_definition is not None:
            entity.set_pattern_definition(pattern_definition)
            entity.dxf.pattern_scale = float(entity.dxf.pattern_scale) * pattern_scale
        self.result.approximated[entity.dxftype()] += 1
        self.result.add_issue(
            "information", "hatch_pattern_local",
            "Sampled hatch boundaries and seed points were reprojected; path flags "
            "and holes were retained. " +
            ("Pattern geometry uses the local XY affine transformation for source "
             "to target coordinates; it is not a globally warped pattern. "
             if pattern_definition is not None else
             "The pattern remains a CAD-local definition. ") +
            (f"{split_boundaries} additional loop(s) came from compound source boundaries. "
             if split_boundaries else "") +
            "Obsolete boundary associations were removed.", entity,
        )

    def _leader(self, entity: Any) -> None:
        anchor = self._entity_anchor(entity)
        scale = self._horizontal_display_scale(anchor) if self._scale_display_sizes else 1.0
        points = self._transform_path(entity.vertices, False)
        entity.set_vertices(points)
        for name in ("text_height", "text_width"):
            if entity.dxf.hasattr(name):
                entity.dxf.set(name, float(entity.dxf.get(name)) * scale)
        # Arrowheads use a per-entity DIMASZ override rather than changing shared styles.
        if self._scale_display_sizes:
            override = entity.override()
            arrow_size = float(override.get("dimasz", 0))
            if arrow_size:
                override["dimasz"] = arrow_size * scale
                override.commit()
        self.result.transformed[entity.dxftype()] += 1

    def _mesh(self, entity: Any) -> None:
        points = self.transform_points(entity.vertices)
        for index, point in enumerate(points):
            entity.vertices[index] = point
        self.result.transformed[entity.dxftype()] += 1

    def _local_affine(
        self, entity: Any, issue_code: str = "local_affine_fallback"
    ) -> None:
        entity_type = entity.dxftype()
        anchor = self._entity_anchor(entity)
        matrix = self._local_matrix(anchor)
        entity.transform(matrix)
        self.result.local_affine[entity_type] += 1
        self.result.add_issue(
            "warning",
            issue_code,
            "The object was preserved and transformed with the CRS Jacobian at its anchor. "
            "This is a first-order approximation and cannot reproduce nonlinear distortion across a large object.",
            entity,
        )

    def _archive_unresolved(self, entity: Any, reason: str) -> None:
        """Retain failed curve/proxy source definitions without inventing geometry."""
        if not entity.is_alive or entity.dxftype() not in {"ELLIPSE", "ACAD_PROXY_ENTITY"}:
            return
        record = {"entity_type": entity.dxftype(), "handle": str(entity.dxf.handle),
                  "layer": str(entity.dxf.layer),
                  "layout": getattr(entity.get_layout(), "name", "<unknown>"),
                  "source_epsg": self.job.source_epsg, "status": "unresolved", "reason": reason}
        try:
            from ezdxf.lldxf.tagwriter import TagCollector
            record["source_dxf"] = "".join(tag.dxfstr() for tag in
                TagCollector.dxftags(entity, dxfversion=self.doc.dxfversion))
        except Exception as exc:
            record["archive_error"] = str(exc)
        if entity.dxftype() == "ACAD_PROXY_ENTITY":
            data = entity.proxy_graphic or b""
            record.update(proxy_graphics_bytes=len(data), proxy_graphics_sha256=hashlib.sha256(data).hexdigest())
        self.result.unresolved_entity_sources.append(record)

    def _expand_proxy(self, entity: Any) -> list[Any]:
        """Decode a complete display snapshot before replacing a proxy object."""
        handle = str(entity.dxf.handle)
        if handle in self._prepared_proxy_handles:
            return []
        self._prepared_proxy_handles.add(handle)
        try:
            children, commands, notes = _decode_proxy_graphics(entity, self.cancel)
        except CancelledError:
            raise
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            message = (
                f"Proxy display geometry cannot be converted: {reason.rstrip('. ')}. "
                "To recover this object, open the source drawing in its authoring "
                "CAD application, convert the custom "
                "object to standard CAD entities, save a new DXF/DWG and retry."
            )
            self._archive_unresolved(entity, message)
            self._reject_entity(entity, "proxy_unresolved", message)
            return []
        layout = entity.get_layout()
        if layout is None:
            raise ConversionError("The proxy entity has no owning layout or block.")
        from ezdxf.lldxf.tagwriter import TagCollector

        archive = {
            "source_handle": handle,
            "source_epsg": self.job.source_epsg,
            "source_layout": layout.name,
            "coordinate_frame": (
                "block definition coordinates"
                if layout.is_block_layout
                else "drawing coordinates"
            ),
            "source_dxf_version": self.doc.dxfversion,
            "proxy_graphics_bytes": len(entity.proxy_graphic or b""),
            "proxy_graphics_sha256": hashlib.sha256(
                entity.proxy_graphic or b""
            ).hexdigest(),
            "commands": commands,
            "source_dxf": "".join(
                tag.dxfstr()
                for tag in TagCollector.dxftags(entity, dxfversion=self.doc.dxfversion)
            ),
        }
        # Register children before binding so failures can remove all partial
        # replacements, including children inserted before the failing one.
        for child in children:
            self.cancel.check()
            for name in (
                "invisible",
                "transparency",
                "material_handle",
                "plotstyle_enum",
                "plotstyle_handle",
            ):
                if entity.dxf.hasattr(name):
                    child.dxf.set(name, entity.dxf.get(name))
            self._add_output(layout, child)
            _copy_xdata(entity, child)
        archive["replacement_handles"] = [str(child.dxf.handle) for child in children]
        self.result.proxy_entity_sources.append(archive)
        self.result.add_issue(
            "warning",
            "proxy_graphics_materialized",
            f"Replaced the proxy with {len(children)} native display entities. "
            "Its proprietary editing behaviour and opaque application coordinates "
            "were not reprojected. Original proxy tags are recorded in "
            "proxy_entity_sources in the JSON report. " + " ".join(notes),
            entity,
        )
        self._discard_entity(entity)
        self.result.exploded["ACAD_PROXY_ENTITY"] += 1
        return children

    def _prepare_proxies(self) -> None:
        """Expand reachable block proxies in their source frame before INSERTs."""
        pending = [self.doc.modelspace()]
        if self.job.transform_paper_space:
            pending.extend(
                layout for layout in self.doc.layouts if layout.name != "Model"
            )
        visited: set[str] = set()
        while pending:
            self.cancel.check()
            layout = pending.pop()
            key = str(layout.block_record_handle)
            if key in visited:
                continue
            visited.add(key)
            for entity in list(layout):
                self.cancel.check()
                kind = entity.dxftype()
                if kind == "ACAD_PROXY_ENTITY":
                    self.transform_entity(entity)
                elif kind == "INSERT":
                    block = entity.block()
                    if block is not None:
                        pending.append(block)
                elif kind == "DIMENSION":
                    name = entity.dxf.get("geometry", "")
                    if name and name in self.doc.blocks:
                        pending.append(self.doc.blocks[name])

    def _composite_problem(self, entity: Any) -> str | None:
        """Inspect virtual copies before an explosion can destroy source content."""
        from ezdxf.xclip import XClip

        pending = [(entity, frozenset())]
        try:
            while pending:
                self.cancel.check()
                current, ancestors = pending.pop()
                entity_type = current.dxftype()
                if entity_type == "INSERT":
                    if XClip(current).has_clipping_path:
                        return "The block contains an XCLIP boundary that cannot be preserved by explosion."
                    block_name = str(current.dxf.name).casefold()
                    if block_name in ancestors:
                        return (
                            f"Recursive block reference detected: {current.dxf.name}."
                        )
                    ancestry = ancestors | {block_name}
                    block = current.block()
                    if block is None:
                        return f"Block definition is missing: {current.dxf.name}."
                    # Some non-copyable entities expose an empty virtual-entity
                    # iterator, so ezdxf does not invoke its skip callback.
                    for member in block:
                        self.cancel.check()
                        try:
                            member.copy()
                        except Exception as exc:
                            return f"Block content cannot be copied completely: {member.dxftype()}: {exc}"
                    skipped: list[str] = []

                    def record_skip(
                        child: Any, reason: str, entries: list[str] = skipped
                    ) -> None:
                        entries.append(f"{child.dxftype()}: {reason}")

                    references = (
                        current.multi_insert() if current.mcount > 1 else (current,)
                    )
                    for reference in references:
                        self.cancel.check()
                        for child in reference.virtual_entities(
                            skipped_entity_callback=record_skip
                        ):
                            self.cancel.check()
                            if child.dxftype() in self.COMPOSITE_TYPES:
                                pending.append((child, ancestry))
                        if skipped:
                            return (
                                "Block content cannot be exploded completely: "
                                + "; ".join(skipped)
                            )
                else:
                    content = getattr(current, "virtual_block_content", None)
                    if content is None and not current.is_virtual:
                        content = current.get_geometry_block()
                    if content is None:
                        return "The dimension has no accessible rendered geometry."
                    expected_count = len(content)
                    children = list(current.virtual_entities())
                    if not children or len(children) != expected_count:
                        return "The dimension geometry is empty or contains objects that cannot be copied."
                    geometry = str(current.dxf.get("geometry", "")).casefold()
                    if geometry and geometry in ancestors:
                        return f"Recursive dimension geometry detected: {geometry}."
                    ancestry = ancestors | {geometry} if geometry else ancestors
                    for child in children:
                        if child.dxftype() in self.COMPOSITE_TYPES:
                            pending.append((child, ancestry))
        except CancelledError:
            raise
        except Exception as exc:
            return f"Composite geometry could not be inspected safely: {exc}"
        return None

    def _explode_composite(self, entity: Any) -> list[Any]:
        entity_type = entity.dxftype()
        problem = self._composite_problem(entity)
        if problem is not None:
            self._reject_entity(entity, "composite_unresolved", problem)
            return []
        layout = entity.get_layout()
        if layout is None:
            raise ConversionError("Composite entity is not assigned to a layout.")
        # ezdxf can bind several children before an explosion fails. The adapter
        # records every addition so best-effort cleanup cannot leave fragments.
        exploded = list(
            entity.explode(target_layout=_TrackedOutputLayout(layout, self._add_output))
        )
        self.result.exploded[entity_type] += 1
        return exploded

    def _explode_multileader(self, entity: Any) -> list[Any]:
        layout = entity.get_layout()
        if layout is None:
            raise ConversionError("Multileader is not assigned to a layout.")
        children = list(entity.virtual_entities())
        if not children:
            raise ConversionError("Multileader has no accessible rendered geometry.")
        for child in children:
            self.cancel.check()
            if child.dxftype() in {"MULTILEADER", "MLEADER"}:
                raise ConversionError("Recursive multileader display geometry.")
            for name in ("invisible", "transparency", "material_handle",
                         "plotstyle_enum", "plotstyle_handle"):
                if entity.dxf.hasattr(name) and child.dxf.is_supported(name):
                    child.dxf.set(name, entity.dxf.get(name))
            self._add_output(layout, child)
            _copy_xdata(entity, child)
        self.result.add_issue(
            "warning", "multileader_materialized",
            f"Replaced the multileader with {len(children)} source-coordinate display "
            "entities for individual reprojection. Native multileader editing "
            "semantics are not retained; unsupported child geometry is still reported.",
            entity,
        )
        self.result.exploded[entity.dxftype()] += 1
        self._discard_entity(entity)
        return children

    def _rollback_failed_entity(
        self, entity: Any, counters: dict[str, Any], lengths: dict[str, int]
    ) -> None:
        """Remove the complete failed leaf and partial outputs, without bridging vertices."""
        try:
            for child in reversed(self._active_outputs):
                self._discard_entity(child)
            self._discard_entity(entity)
        except Exception as exc:
            raise ConversionError(
                f"Failed-object cleanup could not be completed: {exc}. No output was published."
            ) from exc
        for name, counter in counters.items():
            setattr(self.result, name, counter)
        for name, length in lengths.items():
            del getattr(self.result, name)[length:]

    def transform_entity(self, entity: Any) -> list[Any]:
        self.cancel.check()
        entity_type = entity.dxftype()
        handle = str(entity.dxf.get("handle", "") or "")
        layout_name = getattr(entity.get_layout(), "name", "<unknown>")
        previous_outputs = self._active_outputs
        self._active_outputs = []
        previous_origin = self._active_origin
        self._active_origin = self._output_origins.get(
            handle, (entity_type, handle, layout_name)
        )
        counters_before = (
            {name: getattr(self.result, name).copy() for name in self.COUNTER_FIELDS}
            if not self.job.strict_unresolved
            else {}
        )
        lengths_before = (
            {name: len(getattr(self.result, name)) for name in self.ARCHIVE_FIELDS}
            if not self.job.strict_unresolved
            else {}
        )
        try:
            if entity_type == "ACAD_PROXY_ENTITY":
                return self._expand_proxy(entity)
            if entity_type in self.COMPOSITE_TYPES:
                return self._explode_composite(entity)
            if entity_type in {"MULTILEADER", "MLEADER"}:
                return self._explode_multileader(entity)
            self._rescale_entity_linetype(entity)
            if entity_type in self.EXACT_POINT_TYPES:
                self._exact_points(entity)
            elif entity_type in self.CURVE_TYPES or entity_type == "POLYLINE":
                self._polyline_or_curve(entity)
            elif entity_type in {"HATCH", "MPOLYGON"}:
                self._hatch(entity)
            elif entity_type == "LEADER":
                self._leader(entity)
            elif entity_type == "MESH":
                self._mesh(entity)
            elif entity_type == "VIEWPORT":
                self._local_affine(entity, "viewport_local_affine")
            elif entity_type in self.NON_GEOMETRIC_TYPES:
                # These metadata records do not expose display geometry here.
                self.result.transformed[f"{entity_type}_PRESERVED"] += 1
            else:
                self._local_affine(entity)
        except CancelledError:
            raise
        except CoordinateTransformationError as exc:
            source_type, source_handle, source_layout = self._active_origin
            layer = str(entity.dxf.get("layer", "0")) if entity.is_alive else "<removed>"
            context = (f"Object: {entity_type}, handle {handle}, layer {layer!r}, "
                       f"layout {layout_name}. Original: {source_type} handle "
                       f"{source_handle} in {source_layout}.")
            if (isinstance(exc, GridCoverageError) and self.job.skip_outside_grid
                    and not self.job.strict_unresolved):
                self._rollback_failed_entity(entity, counters_before, lengths_before)
                self.result.skipped_outside_grid[entity_type] += 1
                self.result.outside_grid_objects.append({
                    "entity_type": entity_type, "handle": handle, "layer": layer,
                    "layout": layout_name, "source_handle": source_handle,
                    "source_entity_type": source_type, "source_layout": source_layout,
                    "reason": "Outside mandatory grid coverage",
                    **{k: v for k, v in exc.details.items() if k != "bounds_degrees"},
                })
                location = exc.details.get("source_wcs", exc.details.get("input_coordinates"))
                self._record_omission(
                    entity_type, handle, layout_name,
                    f"Outside mandatory grid coverage at source WCS {location}; the complete "
                    "object was skipped under the selected cleanup policy. Grid-stage "
                    "coordinates are recorded in outside_grid_objects; grid bounds are "
                    "recorded with the coordinate operation.",
                )
                self.result.issues[-1].code = "outside_grid_object_skipped"
                return []
            message = f"{exc}\n{context} No output for this drawing was published."
            if entity.is_alive:
                self.result.add_issue("error", "coordinate_operation_failed", message, entity)
            self.log(message)
            details = {"details": exc.details} if isinstance(exc, GridCoverageError) else {}
            raise type(exc)(message, **details) from exc
        except Exception as exc:
            reason = str(exc).strip() or type(exc).__name__
            self._archive_unresolved(entity, reason)
            if not self.job.strict_unresolved:
                self._rollback_failed_entity(entity, counters_before, lengths_before)
                self.result.unresolved[entity_type] += 1
                self._record_omission(entity_type, handle, layout_name, reason)
                return []
            self.result.unresolved[entity_type] += 1
            self.result.issues.append(
                EntityIssue(
                    severity="error",
                    code="entity_transformation_failed",
                    message=f"Drawing publication stopped after a failed entity transformation: {reason}",
                    layout=layout_name,
                    entity_type=entity_type,
                    handle=handle,
                )
            )
            raise ConversionError(
                f"Could not safely transform {entity_type} (handle {handle or 'unknown'}): "
                f"{reason.rstrip('. ')}. "
                "No output for this drawing was published because the object may have been partly changed."
            ) from exc
        finally:
            self._active_outputs = previous_outputs
            self._active_origin = previous_origin
        return []

    def transform_layout(self, layout: Any) -> None:
        previous = self._defer_deletion
        self._defer_deletion = True
        try:
            self._transform_layout(layout)
        finally:
            self._defer_deletion = previous
            self._purge_discarded_entities()

    def _transform_layout(self, layout: Any) -> None:
        # Initial weights reflect vertex work; exploded children share their parent's
        # remaining weight, so discovering block contents cannot reverse progress.
        def weight(entity: Any) -> float:
            kind = entity.dxftype()
            if kind == "LWPOLYLINE":
                return max(1, len(entity))
            if kind in {"POLYLINE", "MESH", "LEADER"}:
                return max(1, len(entity.vertices))
            if kind in {"HATCH", "MPOLYGON"}:
                return max(8, sum(len(p.vertices) if hasattr(p, "vertices") else
                                  len(p.edges) * 8 for p in entity.paths))
            if kind in {"INSERT", "DIMENSION", "MULTILEADER", "MLEADER"}:
                return 16.0
            return 8.0 if kind in self.CURVE_TYPES else 1.0

        pending = deque((entity, float(weight(entity))) for entity in layout)
        self._progress_total = max(1.0, sum(w for _, w in pending))
        self._progress_completed = 0.0
        processed = 0
        while pending:
            self.cancel.check()
            # Batch only native input points/line probes; never change entities here.
            # Failed speculative prefetch is replayed by the normal entity handler,
            # which attaches its exact layer, handle and source provenance.
            if processed % 128 == 0:
                probes = []
                line_pairs = []
                from itertools import islice
                for candidate, _ in islice(pending, 0, 128):
                    if not candidate.is_alive:
                        continue
                    kind = candidate.dxftype()
                    if kind == "POINT":
                        probes.append(candidate.dxf.location)
                    elif kind == "LINE":
                        line_pairs.append((candidate.dxf.start, candidate.dxf.end))
                if len(probes) >= 16:
                    try:
                        self.transform_points(probes)
                    except CoordinateTransformationError:
                        pass  # The owning entity applies the configured failure policy.
                if len(line_pairs) >= 16:
                    try:
                        self._prime_edge_pairs(line_pairs)
                    except CoordinateTransformationError:
                        pass  # Never omit a whole batch because one point failed.
            entity, entity_weight = pending.popleft()
            self._progress_current_weight = entity_weight
            self._entity_label = (f"{layout.name}: {processed:,} object(s) processed; "
                                  f"{len(pending) + 1:,} queued — "
                                  f"{entity.dxftype() if entity.is_alive else 'removed'} "
                                  f"{entity.dxf.handle if entity.is_alive else ''}")
            self._entity_progress(0.0)
            if entity.is_alive:
                children = self.transform_entity(entity)
            else:
                children = []
            processed += 1
            if children:
                # Preflight/explosion is assigned 10% of this composite's work budget.
                own = entity_weight * 0.1
                child_weights = [float(weight(child)) for child in children]
                total = sum(child_weights)
                tasks = [(child, (entity_weight - own) * w / total)
                         for child, w in zip(children, child_weights, strict=True)]
                pending.extendleft(reversed(tasks))
                self._progress_completed += own
            else:
                self._progress_completed += entity_weight
            self._entity_progress(0.0)
        self._emit_progress(self._progress_layout_base + self._progress_layout_span,
                            f"{layout.name}: {processed:,} object(s) processed", force=True)

    def run(self) -> None:
        self.log(f"Coordinate operation: {self.operation_description}")
        if self.coordinate_operation.grids:
            for grid in self.coordinate_operation.grids:
                self.log(
                    f"Required local NTv2 grid: {grid['path']} ({grid['direction']})"
                )
                self.log(f"Grid source-datum coverage (degrees): "
                         f"{[part['bounds_degrees'] for part in grid['subgrids']]}")
            self.log(
                "Horizontal grid correction active; no vertical datum correction is applied."
            )
        else:
            self.log(f"Stated transformation accuracy: {self.operation_accuracy}")
        if not self.coordinate_operation.best_available:
            self.log(
                "WARNING: PROJ reports that a higher-accuracy coordinate operation is unavailable, "
                "normally because an official transformation grid is not installed. The best "
                "currently installed non-ballpark operation will be used and recorded in the report."
            )
        self.result.input_entity_count = len(self.doc.modelspace())
        if self.job.skip_outside_grid and not self.job.strict_unresolved:
            self.log("Out-of-grid cleanup enabled: skip complete affected objects, report "
                     "their source handles, and continue. In-coverage origins are retained.")
        self._emit_progress(0.0, "Preparing blocks and proxy graphics", force=True)
        self._prepare_proxies()
        layouts = [self.doc.modelspace()]
        if self.job.transform_paper_space:
            layouts.extend(layout for layout in self.doc.layouts if layout.name != "Model")
        for index, layout in enumerate(layouts):
            self._progress_layout_base = 0.06 + 0.82 * index / len(layouts)
            self._progress_layout_span = 0.82 / len(layouts)
            self.transform_layout(layout)
        self.result.output_entity_count = len(self.doc.modelspace())
        if self.result.input_entity_count and not self.result.output_entity_count:
            raise ConversionError(
                "No model-space objects survived conversion. An empty output would "
                "be misleading, so no drawing was published. See the report for omissions."
            )

        # Store machine-readable CRS provenance inside the DXF header.
        custom = self.doc.header.custom_vars
        for tag, value in (
            ("CAD_EPSG_SOURCE", f"EPSG:{self.job.source_epsg}"),
            ("CAD_EPSG_TARGET", f"EPSG:{self.job.target_epsg}"),
            ("CAD_EPSG_OPERATION", self.operation_description[:240]),
            ("CAD_EPSG_TOOL", f"{APP_NAME} {APP_VERSION}"),
        ):
            with contextlib.suppress(Exception):
                if custom.has_tag(tag):
                    custom.replace(tag, value)
                else:
                    custom.append(tag, value)

        # Projected and geocentric XYZ use metres; angular XY has no CAD unit code.
        self.doc.header["$INSUNITS"] = 0 if self.target_crs.is_geographic else 6
        if self._scale_display_sizes and self._reference_source_point is not None:
            pdsize = float(self.doc.header.get("$PDSIZE", 0.0))
            if pdsize > 0:
                scale = self._horizontal_display_scale(self._reference_source_point)
                self.doc.header["$PDSIZE"] = pdsize * scale
        self._emit_progress(0.9, "Computing target extents and fitting the CAD startup view", force=True)
        self.result.display_setup = _prepare_output_display(
            self.doc, self.target_crs.is_geographic, self.cancel
        )
        self.result.drawing_warnings.extend(self.result.display_setup["warnings"])
        self.result.drawing_warnings.extend(self.coordinate_operation.warnings)
        samples = self._roundtrip_samples
        self.result.numerical_checks = {
            "coordinate_evaluations": self._point_transform_count,
            "exact_coordinate_cache_hits": self._cache_hits,
            "local_matrix_cache_hits": self._matrix_cache_hits,
            "vectorized_edge_checks_reused": self._edge_cache_hits,
            "grid_failure_cache_hits": self._grid_failure_cache_hits,
            "vectorized_coordinate_batches": self._batch_calls,
            "direct_linear_polyline_batches": self._linear_polyline_batches,
            "coordinate_cache_limit": POINT_CACHE_LIMIT,
            "roundtrip_sample_count": len(samples),
            "maximum_horizontal_closure_m": max((v.get("horizontal_closure_m", 0) for v in samples), default=0),
            "maximum_vertical_closure_m": max((v.get("vertical_closure_m", 0) for v in samples), default=0),
            "one_sided_derivative_probes": self._one_sided_derivatives,
            "source_curve_tolerance": self.job.curve_tolerance,
            "source_curve_tolerance_unit": "degree" if self.source_crs.is_geographic else "metre",
            "adaptive_reprojection_tolerance_m": self.job.reprojection_tolerance_m,
            "samples": samples,
            "scope": "Numerical closure of the selected operation; not surveyed accuracy or proof of every CAD shape.",
        }
        bounds = self.result.display_setup["geometry"].get("bounds")
        self.log(f"Model-space objects: {self.result.input_entity_count:,} input -> "
                 f"{self.result.output_entity_count:,} output.")
        if self.result.omitted:
            self.log("Omitted objects: " + ", ".join(
                f"{kind}: {count:,}" for kind, count in sorted(self.result.omitted.items())))
        if bounds:
            self.log(f"Output bounds: {bounds['minimum']} -> {bounds['maximum']}")
        self.log("Output startup view reset to WCS/top view and fitted to target XY geometry.")
        self._emit_progress(1.0, "Geometry and startup view prepared", force=True)


def _safe_output_path(source: Path, job: ConversionJob) -> Path:
    name = f"{source.stem}{job.output_suffix}.{job.output_format}"
    target = Path(job.output_directory) / name
    if target.resolve() == source.resolve():
        raise ConversionError(
            "Input and output paths are identical. Use an output suffix or another folder."
        )
    if target.exists() and not job.overwrite:
        raise ConversionError(
            f"Output already exists and overwrite is disabled: {target}"
        )
    return target


def _atomic_copy(source: Path, target: Path, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise ConversionError(f"Output already exists: {target}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if overwrite:
            os.replace(temporary, target)
        elif os.name == "nt":
            # Windows rename refuses an existing destination atomically.
            os.rename(temporary, target)
        else:
            # link() publishes without replacing a concurrently created file.
            os.link(temporary, target)
    except FileExistsError as exc:
        raise ConversionError(f"Output already exists: {target}") from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _fast_entity_box(entity: Any) -> Any:
    """Exact vertex bounds for already linear native geometry; normal bbox otherwise.

    Bulges, widths, thickness and complex entities still use ezdxf's existing
    bounding-box implementation. Optional hatch seeds are NOT visible geometry.
    """
    from ezdxf.math import BoundingBox
    kind = entity.dxftype()
    if kind in {"LINE", "POINT", "SOLID", "TRACE"} and entity.dxf.get("thickness", 0):
        return ezdxf_bbox.extents([entity], fast=True)
    if kind == "LINE":
        return BoundingBox((entity.dxf.start, entity.dxf.end))
    if kind == "POINT":
        return BoundingBox((entity.dxf.location,))
    if kind == "3DFACE":
        return BoundingBox(entity.dxf.get(f"vtx{i}") for i in range(4))
    if kind in {"SOLID", "TRACE"}:
        return BoundingBox(entity.wcs_vertices())
    if kind == "LWPOLYLINE":
        rows = _lwpolyline_rows(entity)
        if (not entity.dxf.const_width and not entity.dxf.thickness
                and not np.any(rows[:, 2:])):
            if not len(rows):
                return BoundingBox()
            if tuple(entity.dxf.extrusion) == (0.0, 0.0, 1.0):
                if not np.isfinite(rows[:, :2]).all() or not math.isfinite(entity.dxf.elevation):
                    raise ConversionError("Non-finite polyline bounds.")
                lo, hi = rows[:, :2].min(axis=0), rows[:, :2].max(axis=0)
                z = float(entity.dxf.elevation)
                return BoundingBox(((lo[0], lo[1], z), (hi[0], hi[1], z)))
            return BoundingBox(entity.vertices_in_wcs())
    if kind == "POLYLINE" and entity.get_mode() in {"AcDb3dPolyline", "AcDbPolygonMesh", "AcDbPolyFaceMesh"}:
        return BoundingBox(v.dxf.location for v in entity.vertices if not v.is_face_record)
    if kind == "MESH":
        return BoundingBox(entity.vertices)
    if kind in {"HATCH", "MPOLYGON"}:
        from ezdxf.entities.boundary_paths import PolylinePath
        if all(isinstance(path, PolylinePath) and not path.has_bulge() for path in entity.paths):
            ocs, elevation = entity.ocs(), float(entity.dxf.elevation.z)
            return BoundingBox(ocs.to_wcs((v[0], v[1], elevation))
                               for path in entity.paths for v in path.vertices)
    return ezdxf_bbox.extents([entity], fast=True)


def _modelspace_summary(document: Any, cancel: CancellationToken | None = None) -> dict[str, Any]:
    """Finite geometric bounds, not the possibly stale stored EXTMIN/EXTMAX.

    ezdxf bounding boxes can be unavailable for proprietary/ACIS/infinite objects.
    Such objects are counted explicitly; their presence is not proof of a visible
    primitive. Fast curve/text boxes are approximate, and are labelled as such.
    """
    from ezdxf.math import BoundingBox

    all_box, visible_box = BoundingBox(), BoundingBox()
    bounded = visible_bounded = hidden = 0
    unsupported: Counter[str] = Counter()
    visibility: dict[str, bool] = {}
    errors: list[dict[str, str]] = []
    samples: list[dict[str, Any]] = []
    for index, entity in enumerate(document.modelspace()):
        if cancel is not None and index % 64 == 0:
            cancel.check()
        kind = entity.dxftype()
        layer_name = str(entity.dxf.get("layer", "0"))
        key = layer_name.casefold()
        if key not in visibility:
            try:
                layer = document.layers.get(layer_name)
                visibility[key] = not (layer.is_off() or layer.is_frozen())
            except Exception:
                visibility[key] = True  # audit will identify missing layer entries
        visible = visibility[key] and not entity.dxf.get("invisible", 0)
        hidden += int(not visible)
        try:
            box = _fast_entity_box(entity)
        except Exception as exc:
            unsupported[kind] += 1
            if len(errors) < 20:
                errors.append({"type": kind, "handle": str(entity.dxf.handle),
                               "reason": str(exc) or type(exc).__name__})
            continue
        if not box.has_data:
            unsupported[kind] += 1
            continue
        low, high = box.extmin, box.extmax
        if not all(math.isfinite(float(v)) for p in (low, high) for v in p):
            raise ConversionError(
                f"Non-finite output bounds for {kind} handle {entity.dxf.handle}. "
                "The drawing cannot be verified safely."
            )
        all_box.extend((low, high))
        bounded += 1
        if visible:
            visible_box.extend((low, high))
            visible_bounded += 1
        if len(samples) < 8:
            samples.append({"type": kind, "handle": str(entity.dxf.handle),
                            "minimum": list(low), "maximum": list(high)})

    def pack(box: Any) -> dict[str, list[float]] | None:
        if not box.has_data:
            return None
        return {"minimum": list(box.extmin), "maximum": list(box.extmax),
                "size": list(box.size)}

    return {
        "method": "ezdxf finite geometric bounding boxes (fast/approximate, not stored header extents)",
        "modelspace_entities": len(document.modelspace()),
        "bounded_entity_count": bounded,
        "visible_bounded_entity_count": visible_bounded,
        "hidden_entity_count": hidden,
        "unbounded_or_unsupported_types": dict(sorted(unsupported.items())),
        "bounding_box_errors": errors,
        "bounds": pack(all_box),
        "visible_bounds": pack(visible_box),
        "sample_entity_bounds": samples,
        "visibility_note": "Layer off/frozen and entity invisible flags; this is not a CAD render test.",
    }


def _saved_model_view(document: Any) -> dict[str, Any]:
    views = document.viewports.get_config("*Active")
    v = views[0] if views else None
    return {
        "tilemode": int(document.header.get("$TILEMODE", 1)),
        "active_model_viewport_count": len(views),
        "center": list(v.dxf.center) if v is not None else None,
        "height": float(v.dxf.height) if v is not None else None,
        "aspect_ratio": float(v.dxf.aspect_ratio) if v is not None else None,
        "direction": list(v.dxf.direction) if v is not None else None,
        "target": list(v.dxf.target) if v is not None else None,
        "view_mode": int(v.dxf.view_mode) if v is not None else None,
        "view_twist": float(v.dxf.view_twist) if v is not None else None,
        "stored_extmin": list(document.header.get("$EXTMIN", (0, 0, 0))),
        "stored_extmax": list(document.header.get("$EXTMAX", (0, 0, 0))),
        "point_size": float(document.header.get("$PDSIZE", 0)),
    }


def _prepare_output_display(document: Any, geographic: bool,
                            cancel: CancellationToken) -> dict[str, Any]:
    """Replace stale model-space camera/limits using target XY, irrespective of Z."""
    geometry = _modelspace_summary(document, cancel)
    warnings_out: list[str] = []
    if geometry["unbounded_or_unsupported_types"]:
        warnings_out.append(
            "Some objects have no bounding box (possibly empty, infinite or unsupported). "
            "See unbounded_or_unsupported_types; the view is fitted to bounded geometry."
        )
    bounds = geometry["bounds"]
    if not bounds:
        raise ConversionError(
            "No finite model-space geometry could be located for the output view. "
            "No drawing was published; inspect the input model space and the report."
        )
    view_bounds = geometry["visible_bounds"] or bounds
    if not geometry["visible_bounded_entity_count"]:
        warnings_out.append(
            "All bounded output geometry is hidden by existing layer/entity settings. "
            "Those settings were preserved. Enable the intended layers in CAD to view it."
        )
    low, high = view_bounds["minimum"], view_bounds["maximum"]
    dx, dy = high[0] - low[0], high[1] - low[1]
    center = (low[0] + dx / 2.0, low[1] + dy / 2.0)
    # A single point still needs a nonzero, unit-aware viewport.
    span = max(dx, dy)
    if span <= 0:
        span = 1e-5 if geographic else 1.0
    margin = max(span * 0.08, 32 * math.ulp(max(1.0, abs(center[0]), abs(center[1]))))
    # A fresh full-window view, not the aspect ratio of a stale split viewport.
    # CAD may adapt this to its current window; no geometry coordinates are scaled.
    aspect = 1.6
    height = max(dy + 2 * margin, (dx + 2 * margin) / aspect)
    if not math.isfinite(height) or height <= 0:
        raise ConversionError("Output XY extents cannot define a finite startup view.")
    viewport = document.set_modelspace_vport(
        height, center,
        dxfattribs={
            "direction": (0, 0, 1), "target": (0, 0, 0),
            "view_twist": 0.0, "view_mode": 0,
            "front_clipping": 0.0, "back_clipping": 0.0,
            "aspect_ratio": aspect, "lower_left": (0, 0), "upper_right": (1, 1),
            "snap_on": 0, "grid_on": 0,
        },
    )
    model = document.modelspace()
    # Explicit WCS attributes in both the current view and Model LAYOUT avoid
    # restoring a source UCS in CAD readers that consult the layout object.
    for owner in (viewport, model):
        for key, value in (("ucs_origin", (0, 0, 0)), ("ucs_xaxis", (1, 0, 0)),
                           ("ucs_yaxis", (0, 1, 0)), ("ucs_ortho_type", 0)):
            if owner.dxf.is_supported(key):
                owner.dxf.set(key, value)
        for key in ("ucs_handle", "base_ucs_handle"):
            if owner.dxf.is_supported(key):
                owner.dxf.discard(key)
    document.header["$REGENMODE"] = 1
    model.dxf.extmin, model.dxf.extmax = bounds["minimum"], bounds["maximum"]
    model.dxf.limmin = (low[0] - margin, low[1] - margin)
    model.dxf.limmax = (high[0] + margin, high[1] + margin)
    # ezdxf synchronizes these from LAYOUT on save. Set both now for consistency.
    document.header["$EXTMIN"] = model.dxf.extmin
    document.header["$EXTMAX"] = model.dxf.extmax
    document.header["$LIMMIN"] = model.dxf.limmin
    document.header["$LIMMAX"] = model.dxf.limmax
    document.header["$TILEMODE"] = 1
    document.header["$LIMCHECK"] = 0
    if geographic:
        document.header["$LUNITS"] = 2  # decimal coordinates, NOT degrees/minutes/seconds
        document.header["$LUPREC"] = 8
    return {
        "startup_view": "Model space / WCS / orthographic top / fitted to target XY",
        "z_used_for_zoom_height": False,
        "view_bounds_source": "visible bounded geometry" if geometry["visible_bounds"] else "all bounded geometry",
        "paper_space_note": "Paper-space frames/views and saved named views are not automatically refitted.",
        "geometry": geometry, "saved_view": _saved_model_view(document),
        "warnings": warnings_out,
    }


def _preview_point_size(document: Any) -> float:
    """A positive fractional PDSIZE is a real size, not an integer >= one."""
    value = float(document.header.get("$PDSIZE", 0.0))
    if math.isfinite(value) and value > 0:
        return value
    # Screen-relative sizes need a display-space approximation for this backend.
    # Use XY extent only: preserved Z is in metres even with longitude/latitude XY.
    box = ezdxf_bbox.extents(document.modelspace(), fast=True)
    span = max(box.size.x, box.size.y) if box.has_data else 1.0
    fraction = abs(value) / 100.0 if math.isfinite(value) and value < 0 else 0.01
    size = span * fraction
    return size if math.isfinite(size) and size > 0 else 1.0


def _coordinate_check_values(entity: Any) -> Iterator[Any] | None:
    """Expose semantic WCS positions, not the presence of optional DXF tags."""
    kind = entity.dxftype()
    if kind == "POINT":
        return iter((Vec3(entity.dxf.location),))
    if kind == "LINE":
        return iter((Vec3(entity.dxf.start), Vec3(entity.dxf.end)))
    if kind == "3DFACE":
        return (Vec3(entity.dxf.get(f"vtx{i}")) for i in range(4))
    if kind in {"SOLID", "TRACE"}:
        ocs = entity.ocs()
        return (ocs.to_wcs(entity.dxf.get(f"vtx{i}")) for i in range(4))
    if kind == "LWPOLYLINE":
        return entity.vertices_in_wcs()
    if kind == "POLYLINE":
        if entity.is_poly_face_mesh:
            return (Vec3(v.dxf.location) for v in entity.vertices if not v.is_face_record)
        return entity.points_in_wcs()
    if kind in {"LEADER", "MESH"}:
        return (Vec3(p) for p in entity.vertices)
    if kind in {"HATCH", "MPOLYGON"}:
        if any(not hasattr(path, "vertices") for path in entity.paths):
            return None
        ocs, elevation = entity.ocs(), float(entity.dxf.elevation.z)
        return (ocs.to_wcs((x, y, elevation)) for path in entity.paths for x, y, _ in path.vertices)
    if kind in {"TEXT", "ATTRIB", "ATTDEF"}:
        # DXF's first/second alignment tags do not always both place the text.
        # LEFT uses insert; other ordinary alignments use align_point; FIT and
        # ALIGNED need both. A CAD writer may omit/recompute the unused tag.
        _align, first, second = entity.get_placement()
        ocs = entity.ocs()
        points = (first,) if second is None else (first, second)
        return (ocs.to_wcs(p) for p in points)
    if kind == "MTEXT":
        return iter((Vec3(entity.dxf.insert),))
    return None


class SavedGeometryError(ConversionError):
    """A non-equivalent saved object, with structured diagnostic context."""

    def __init__(self, message: str, entity: Any, **details: Any) -> None:
        handle = str(entity.dxf.get("handle", "") or "<unknown>")
        layer = str(entity.dxf.get("layer", "0"))
        layout = getattr(entity.get_layout(), "name", "<unknown>")
        self.verification_failure = {
            "entity_type": entity.dxftype(), "handle": handle,
            "layer": layer, "layout": layout, "reason": message, **details,
        }
        super().__init__(
            f"Saved-geometry verification failed for {entity.dxftype()} handle {handle} "
            f"(layer {layer!r}, layout {layout!r}): {message} "
            "No output for this drawing was published."
        )


def _saved_position_error_m(first: Any, second: Any, geod: Any) -> float:
    """Absolute positional difference, including metre-valued Z for angular XY.

    Invalid data never compares equal, even when identical on both sides. The
    caller reports the owning entity. Geographic inputs are WCS lon/lat, not OCS.
    """
    a, b = Vec3(first), Vec3(second)
    if not all(math.isfinite(value) for value in (*a, *b)):
        return math.inf
    if geod is not None and not (
        -180 <= a.x <= 180 and -90 <= a.y <= 90
        and -180 <= b.x <= 180 and -90 <= b.y <= 90
    ):
        return math.inf
    if a == b:
        return 0.0
    if geod is not None:
        # Physically coincident longitudes across the seam (or at a pole)
        # are not interchangeable vertices of a straight longitude/latitude
        # CAD boundary. Do not turn a world-spanning edge into neutral closure.
        if abs(a.x - b.x) > 180 or (
            (abs(a.y) == 90 or abs(b.y) == 90) and a.x != b.x
        ):
            return math.inf
        error = math.hypot(float(geod.inv(a.x, a.y, b.x, b.y)[2]), a.z - b.z)
    else:
        error = (a - b).magnitude
    return error if math.isfinite(error) else math.inf


def _paired_hatch_verification_groups(
    original: Any, reopened: Any, geod: Any,
    cancel: CancellationToken | None = None,
) -> tuple[Any, Any, list[dict[str, Any]]]:
    """Pair closed loops before interpreting an optional terminal closure record.

    This is read-only. Equal-length loops keep EVERY point. Unequal lengths may
    differ by one terminal point, never an interior point, and only for a closed
    straight boundary. Both its own endpoint gap and the discarded-point-to-
    OTHER-start distance must fit the existing 0.00001 m publication threshold.
    The caller subsequently checks every remaining paired vertex in order.

    No default isclose(), relative coordinate tolerance, angular tolerance,
    simplification, cyclic reordering, loss of holes or writer-success bypass.
    """
    from itertools import islice

    groups: list[list[tuple[str, Iterable[Any]]]] = [[], []]
    raw_counts: list[list[int]] = [[], []]
    comparison_counts: list[list[int]] = [[], []]
    changes: list[dict[str, Any]] = []
    systems = (original.ocs(), reopened.ocs())
    elevations = (float(original.dxf.elevation.z), float(reopened.dxf.elevation.z))

    def wcs(row: Any, side: int) -> Any:
        return systems[side].to_wcs((row[0], row[1], elevations[side]))

    # Freeze the frame/elevation per iterator: late binding would evaluate all
    # groups in the final boundary's frame when the iterators are consumed later.
    def positions(rows: Any, count: int, side: int) -> Iterator[Any]:
        ocs, elevation = systems[side], elevations[side]
        return (ocs.to_wcs((row[0], row[1], elevation)) for row in islice(rows, count))

    for index, paths in enumerate(zip(original.paths, reopened.paths, strict=True)):
        if cancel is not None:
            cancel.check()
        rows = (paths[0].vertices, paths[1].vertices)
        counts = [len(rows[0]), len(rows[1])]
        stops = list(counts)
        role = f"hatch boundary {index + 1}"
        if counts[0] != counts[1]:
            long_side = int(counts[1] > counts[0])
            short_side = 1 - long_side
            count = counts[long_side]
            gap = cross_gap = math.inf
            eligible = (
                abs(counts[0] - counts[1]) == 1 and count >= 4
                and bool(paths[0].is_closed) and bool(paths[1].is_closed)
                and all(float(row[2]) == 0.0 for path_rows in rows for row in path_rows)
            )
            if eligible:
                first = wcs(rows[long_side][0], long_side)
                last = wcs(rows[long_side][-1], long_side)
                counterpart = wcs(rows[short_side][0], short_side)
                gap = _saved_position_error_m(first, last, geod)
                cross_gap = _saved_position_error_m(last, counterpart, geod)
            if not eligible or gap > 1e-5 or cross_gap > 1e-5:
                raise SavedGeometryError(
                    f"{role} count changed: expected {counts[0]}, reopened {counts[1]}. "
                    "This is not a terminal closing point equivalent within 0.00001 m.",
                    original, coordinate_group=role,
                    expected_coordinate_count=counts[0], reopened_coordinate_count=counts[1],
                    closure_test_eligible=eligible,
                    closure_gap_m=gap if math.isfinite(gap) else None,
                    terminal_to_counterpart_start_m=cross_gap if math.isfinite(cross_gap) else None,
                    tolerance_m=1e-5,
                )
            stops[long_side] -= 1
            changes.append({
                "coordinate_group": role,
                "normalization": "terminal_closing_point_within_metric_tolerance",
                "longer_representation": "reopened" if long_side else "expected",
                "expected_coordinate_count": counts[0],
                "reopened_coordinate_count": counts[1],
                "closure_gap_m": gap,
                "terminal_to_counterpart_start_m": cross_gap,
                "terminal_wcs": list(last),
                "counterpart_start_wcs": list(counterpart),
                "tolerance_m": 1e-5,
                "drawing_modified": False,
            })
        for side in (0, 1):
            raw_counts[side].append(counts[side])
            comparison_counts[side].append(stops[side])
            groups[side].append((role, positions(rows[side], stops[side], side)))
    notes = [{"stored_boundary_vertex_counts": raw_counts[side],
              "comparison_boundary_vertex_counts": comparison_counts[side]} for side in (0, 1)]
    return (groups[0], notes[0]), (groups[1], notes[1]), changes


def _saved_hatch_snapshot(entity: Any, geod: Any) -> dict[str, Any]:
    """Bounded failure evidence: original/reopened coordinates, not counts alone.

    Small loops are archived in full. Large loops retain indexed head/tail
    records; diagnostic limits never limit coordinate verification itself.
    """
    def encode(value: Any) -> float | str:
        number = float(value)
        return number if math.isfinite(number) else repr(number)

    ocs, elevation = entity.ocs(), float(entity.dxf.elevation.z)
    entries = []
    for index, path in enumerate(entity.paths):
        if index >= 32:
            break
        entry: dict[str, Any] = {"boundary_index": index + 1,
                                "path_type_flags": int(path.path_type_flags)}
        if not hasattr(path, "vertices"):
            entry["representation"] = type(path).__name__
            entries.append(entry)
            continue
        rows, count = path.vertices, len(path.vertices)
        indices = list(range(count)) if count <= 256 else list(range(16)) + list(range(count - 16, count))
        entry.update(is_closed=bool(path.is_closed), vertex_count=count,
                     coordinate_records_complete=count <= 256,
                     ocs_vertices=[{"index": i, "xy_bulge": [encode(v) for v in rows[i]]}
                                   for i in indices])
        if count:
            first = ocs.to_wcs((rows[0][0], rows[0][1], elevation))
            last = ocs.to_wcs((rows[-1][0], rows[-1][1], elevation))
            gap = _saved_position_error_m(first, last, geod)
            entry.update(first_wcs=[encode(v) for v in first],
                         last_wcs=[encode(v) for v in last],
                         closure_gap_m=gap if math.isfinite(gap) else None)
        entries.append(entry)
    return {"boundary_count": len(entity.paths), "boundaries_complete": len(entity.paths) <= 32,
            "elevation": encode(elevation), "extrusion": [encode(v) for v in entity.dxf.extrusion],
            "wcs_xy_units": "degrees" if geod is not None else "metres", "wcs_z_units": "metres",
            "boundaries": entries}


def _verification_groups(entity: Any, cancel: CancellationToken | None = None
                         ) -> tuple[list[tuple[str, Iterable[Any]]], dict[str, Any]] | None:
    """Keep boundary groups separate; normalize only neutral duplicate closure.

    This is a read-only comparison representation. No drawing vertices are
    removed, rounded, simplified, clamped or repaired here. Open paths retain
    every vertex. Width/bulge-bearing polylines retain their exact record count.
    """
    from itertools import islice

    kind = entity.dxftype()
    notes: dict[str, Any] = {}
    if kind in {"TEXT", "ATTRIB", "ATTDEF"}:
        notes["text_alignment"] = entity.get_align_enum().name
        notes["stored_position_tags"] = [
            name for name in ("insert", "align_point") if entity.dxf.hasattr(name)
        ]
    if kind in {"LWPOLYLINE", "POLYLINE"}:
        values = _coordinate_check_values(entity)
        if kind == "LWPOLYLINE":
            count = len(entity)
            same_end = (bool(entity.is_closed) and count > 2
                        and tuple(entity[0][:2]) == tuple(entity[-1][:2]))
            # Most production paths are open or omit the duplicate closing
            # point: do not rescan their widths/bulges unnecessarily.
            neutral = same_end and not entity.has_width and not entity.has_arc
        else:
            if entity.is_polygon_mesh or entity.is_poly_face_mesh:
                return [("mesh vertices", _coordinate_check_values(entity))], notes
            count = len(entity.vertices)
            same_end = (bool(entity.is_closed) and count > 2
                        and entity.vertices[0].dxf.location == entity.vertices[-1].dxf.location)
            neutral = (same_end and not entity.has_width and not entity.has_arc
                       and not (int(entity.dxf.flags) & 6))
        drop_closure = bool(entity.is_closed and neutral and same_end)
        if drop_closure:
            values = islice(values, count - 1)
        notes.update(stored_vertex_count=count, comparison_vertex_count=count - int(drop_closure),
                     duplicate_closing_vertex_ignored=drop_closure)
        return [("polyline vertices", values)], notes
    if kind in {"HATCH", "MPOLYGON"}:
        groups: list[tuple[str, Iterable[Any]]] = []
        counts, normalized = [], []
        ocs, elevation = entity.ocs(), float(entity.dxf.elevation.z)
        for index, path in enumerate(entity.paths):
            if cancel is not None:
                cancel.check()
            if not hasattr(path, "vertices"):
                # Do not accept an arbitrary curve after checking endpoints only.
                # The converter normally writes straight polyline boundary loops.
                return None
            rows = path.vertices
            count = len(rows)
            neutral_closure = (bool(path.is_closed) and count > 3
                               and tuple(rows[0][:2]) == tuple(rows[-1][:2])
                               and float(rows[-1][2]) == 0.0)
            stop = count - int(neutral_closure)
            points = (ocs.to_wcs((row[0], row[1], elevation)) for row in islice(rows, stop))
            groups.append((f"hatch boundary {index + 1}", points))
            counts.append(count)
            normalized.append(stop)
        notes.update(stored_boundary_vertex_counts=counts,
                     comparison_boundary_vertex_counts=normalized)
        return groups, notes
    values = _coordinate_check_values(entity)
    return None if values is None else ([("positions", values)], notes)


def _check_saved_structure(original: Any, reopened: Any) -> None:
    """Reject changed placement semantics or topology despite matching positions."""
    kind = original.dxftype()
    if kind in {"TEXT", "ATTRIB", "ATTDEF"}:
        if original.get_align_enum() != reopened.get_align_enum():
            raise SavedGeometryError("The text alignment mode changed.", original)
        if original.plain_text() != reopened.plain_text():
            raise SavedGeometryError("The text content changed.", original)
    elif kind == "MTEXT":
        if original.dxf.attachment_point != reopened.dxf.attachment_point:
            raise SavedGeometryError("The MTEXT attachment point changed.", original)
    elif kind in {"LWPOLYLINE", "POLYLINE"}:
        if bool(original.is_closed) != bool(reopened.is_closed):
            raise SavedGeometryError("The polyline open/closed flag changed.", original)
        if kind == "POLYLINE" and original.get_mode() != reopened.get_mode():
            raise SavedGeometryError("The polyline/mesh mode changed.", original)
        if kind == "POLYLINE" and original.is_poly_face_mesh:
            def faces(entity: Any) -> list[tuple[int, ...]]:
                return [tuple(int(v.dxf.get(f"vtx{i}", 0)) for i in range(4))
                        for v in entity.vertices if v.is_face_record]
            if faces(original) != faces(reopened):
                raise SavedGeometryError("The polyface face connectivity changed.", original)
        elif kind == "POLYLINE" and original.is_polygon_mesh:
            for field in ("m_count", "n_count", "flags"):
                if getattr(original.dxf, field) != getattr(reopened.dxf, field):
                    raise SavedGeometryError(f"Polygon-mesh {field} changed.", original)
        else:
            # Compare matched bulges in one streaming pass. Positional groups
            # below enforce the full count, including unmatched terminal rows.
            if kind == "LWPOLYLINE":
                changed = any(a[4] != b[4] for a, b in zip(original, reopened))
            else:
                changed = any(a.dxf.bulge != b.dxf.bulge
                              for a, b in zip(original.vertices, reopened.vertices))
            if changed:
                raise SavedGeometryError("The polyline bulge/arc definition changed.", original)
    elif kind in {"HATCH", "MPOLYGON"}:
        if len(original.paths) != len(reopened.paths):
            raise SavedGeometryError(
                f"Boundary count changed: expected {len(original.paths)}, "
                f"reopened {len(reopened.paths)}.", original,
                expected_boundary_count=len(original.paths), reopened_boundary_count=len(reopened.paths))
        for index, (a, b) in enumerate(zip(original.paths, reopened.paths, strict=True)):
            if (int(a.path_type_flags) & 17) != (int(b.path_type_flags) & 17):
                raise SavedGeometryError(f"Boundary {index + 1} classification changed.", original)
            if hasattr(a, "vertices") and hasattr(b, "vertices"):
                if bool(a.is_closed) != bool(b.is_closed):
                    raise SavedGeometryError(f"Boundary {index + 1} open/closed flag changed.", original)
                if any(float(row[2]) != 0.0 for path in (a, b) for row in path.vertices):
                    # Faceted production boundaries have zero bulges. Do not let a
                    # changed curved boundary pass using vertex positions alone.
                    if list(a.vertices) != list(b.vertices):
                        raise SavedGeometryError(f"Boundary {index + 1} bulge definition changed.", original)
        for field in ("solid_fill", "hatch_style"):
            if original.dxf.is_supported(field) and getattr(original.dxf, field) != getattr(reopened.dxf, field):
                raise SavedGeometryError(f"The hatch {field} setting changed.", original)
    elif kind == "MESH":
        if ([tuple(f) for f in original.faces] != [tuple(f) for f in reopened.faces]
                or [tuple(e) for e in original.edges] != [tuple(e) for e in reopened.edges]):
            raise SavedGeometryError("The mesh face/edge connectivity changed.", original)


def _verify_lwpolyline_array(original: Any, reopened: Any, geod: Any,
                             cancel: CancellationToken | None) -> dict[str, Any] | None:
    """All vertices, vectorized in bounded chunks; same semantic closure rules.

    Limited to ordinary WCS lightweight polylines. Tilted OCS and small objects
    keep the generic coordinate-group checker. This is not a sample-based check.
    """
    if (original.dxftype() != "LWPOLYLINE" or len(original) < 16
            or tuple(original.dxf.extrusion) != (0.0, 0.0, 1.0)
            or tuple(reopened.dxf.extrusion) != (0.0, 0.0, 1.0)):
        return None
    if bool(original.is_closed) != bool(reopened.is_closed):
        raise SavedGeometryError("The polyline open/closed flag changed.", original)

    def representation(entity: Any) -> tuple[Any, dict[str, Any]]:
        rows = _lwpolyline_rows(entity)
        count = len(rows)
        duplicate = (bool(entity.is_closed) and count > 2
                     and np.array_equal(rows[0, :2], rows[-1, :2])
                     and not entity.dxf.const_width and not np.any(rows[:, 2:]))
        stop = count - int(duplicate)
        return rows[:stop], {"stored_vertex_count": count, "comparison_vertex_count": stop,
                              "duplicate_closing_vertex_ignored": bool(duplicate)}

    a, before = representation(original)
    b, after = representation(reopened)
    if len(a) != len(b):
        raise SavedGeometryError(
            f"polyline vertices count changed: expected {len(a)}, reopened {len(b)}. "
            "The difference is not an equivalent closing-point representation.", original,
            coordinate_group="polyline vertices", expected_coordinate_count=len(a),
            reopened_coordinate_count=len(b), expected_representation=before,
            reopened_representation=after)
    z1, z2 = float(original.dxf.elevation), float(reopened.dxf.elevation)
    if not math.isfinite(z1) or not math.isfinite(z2):
        raise SavedGeometryError("Non-finite polyline elevation.", original)
    maximum = 0.0
    for begin in range(0, len(a), 4096):
        if cancel is not None:
            cancel.check()
        first, second = a[begin:begin + 4096], b[begin:begin + 4096]
        if not np.array_equal(first[:, 4], second[:, 4]):
            raise SavedGeometryError("The polyline bulge/arc definition changed.", original)
        if not np.isfinite(first[:, :2]).all() or not np.isfinite(second[:, :2]).all():
            raise SavedGeometryError("Non-finite polyline vertices coordinate.", original)
        if geod is not None and any(
                np.any(np.abs(chunk[:, 0]) > 180) or np.any(np.abs(chunk[:, 1]) > 90)
                for chunk in (first, second)):
            raise SavedGeometryError("Polyline coordinate is outside the target CRS domain.", original)
        if np.array_equal(first[:, :2], second[:, :2]) and z1 == z2:
            continue
        if geod is not None:
            _, _, horizontal = geod.inv(first[:, 0], first[:, 1], second[:, 0], second[:, 1])
            differences = np.hypot(horizontal, z1 - z2)
        else:
            dx = first[:, 0] - second[:, 0]
            dy = first[:, 1] - second[:, 1]
            differences = np.sqrt(dx * dx + dy * dy + (z1 - z2) ** 2)
        bad = np.flatnonzero(~np.isfinite(differences) | (differences > 1e-5))
        if len(bad):
            i = int(bad[0]); error = float(differences[i])
            raise SavedGeometryError(
                f"Saved coordinate changed by {error:.9g} m in polyline vertices "
                f"at index {begin + i}; tolerance is 0.00001 m.", original,
                coordinate_group="polyline vertices", coordinate_index=begin + i,
                expected_coordinate=[float(first[i, 0]), float(first[i, 1]), z1],
                reopened_coordinate=[float(second[i, 0]), float(second[i, 1]), z2],
                difference_m=error)
        maximum = max(maximum, float(np.max(differences)))
    return {"compared_coordinates": len(a), "maximum_difference_m": maximum,
            "before": before, "after": after}


def _verify_saved_coordinates(expected: Any, actual: Any, target_crs: Any,
                              cancel: CancellationToken | None = None,
                              progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Verify semantic positions at 0.00001 m without trusting raw tag counts.

    Inactive text alignment fields and neutral terminal closure duplicates may
    differ between serializers. Active placement, boundary grouping, native
    topology and all compared coordinates must still agree. Nothing is skipped
    merely because its verification fails; real geometry loss remains fatal.
    """
    from itertools import zip_longest

    geod = target_crs.get_geod() if target_crs.is_geographic else None
    maximum = 0.0
    entities = points = 0
    unchecked: Counter[str] = Counter()
    normalizations: list[dict[str, Any]] = []
    total = max(1, len(expected.modelspace()))
    model_owner = actual.modelspace().block_record_handle
    missing = object()
    for index, original in enumerate(expected.modelspace()):
        if index % 128 == 0:
            if cancel is not None:
                cancel.check()
            if progress is not None:
                progress(index / total, f"Verifying saved coordinates: {index:,}/{total:,} objects")
        source = _verification_groups(original, cancel)
        if source is None:
            unchecked[original.dxftype()] += 1
            continue
        handle = original.dxf.handle
        reopened = actual.entitydb.get(handle)
        if reopened is None or not reopened.is_alive or reopened.dxftype() != original.dxftype():
            raise SavedGeometryError("The saved entity is missing or its type changed.", original)
        if reopened.dxf.owner != model_owner:
            raise SavedGeometryError("The saved entity is no longer in model space.", original)
        fast = _verify_lwpolyline_array(original, reopened, geod, cancel)
        if fast is not None:
            points += fast["compared_coordinates"]
            maximum = max(maximum, fast["maximum_difference_m"])
            entities += 1
            if fast["before"] != fast["after"]:
                normalizations.append({"entity_type": original.dxftype(), "handle": handle,
                    "expected_representation": fast["before"],
                    "reopened_representation": fast["after"], "semantic_geometry_verified": True})
            continue
        _check_saved_structure(original, reopened)
        closure_checks: list[dict[str, Any]] = []
        if original.dxftype() in {"HATCH", "MPOLYGON"} and all(
            hasattr(path, "vertices") for path in reopened.paths
        ):
            source, target, closure_checks = _paired_hatch_verification_groups(
                original, reopened, geod, cancel)
            for check in closure_checks:
                # Include the optional terminal point's independently checked
                # cross-representation distance in the reported maximum/count.
                maximum = max(maximum, check["terminal_to_counterpart_start_m"])
                points += 1
        else:
            target = _verification_groups(reopened, cancel)
        if target is None:
            raise SavedGeometryError("Saved positional geometry cannot be compared safely.", original)
        source_groups, before = source
        target_groups, after = target
        if len(source_groups) != len(target_groups):
            raise SavedGeometryError("The number of positional groups changed.", original)
        for (role, values), (_, restored) in zip(source_groups, target_groups, strict=True):
            compared = 0
            for a, b in zip_longest(values, restored, fillvalue=missing):
                if a is missing or b is missing:
                    # Count the remaining records only on the error path. The
                    # common success path streams large meshes/polylines.
                    na, nb = compared + int(a is not missing), compared + int(b is not missing)
                    for iterable, side in ((values, "expected"), (restored, "reopened")):
                        extra = 0
                        for _value in iterable:
                            extra += 1
                            if cancel is not None and extra % 4096 == 0:
                                cancel.check()
                        if side == "expected":
                            na += extra
                        else:
                            nb += extra
                    raise SavedGeometryError(
                        f"{role} count changed: expected {na}, reopened {nb}. "
                        "The difference is not an equivalent optional-field or closing-point representation.",
                        original, coordinate_group=role, expected_coordinate_count=na,
                        reopened_coordinate_count=nb, expected_representation=before,
                        reopened_representation=after)
                a, b = Vec3(a), Vec3(b)
                if not all(math.isfinite(v) for v in (*a, *b)):
                    raise SavedGeometryError(f"Non-finite {role} coordinate.", original)
                if geod is not None and not (-180 <= a.x <= 180 and -90 <= a.y <= 90
                                             and -180 <= b.x <= 180 and -90 <= b.y <= 90):
                    raise SavedGeometryError(f"{role} coordinate is outside the target CRS domain.", original)
                if a == b:
                    error = 0.0
                elif geod is not None:
                    error = math.hypot(abs(geod.inv(a.x, a.y, b.x, b.y)[2]), a.z - b.z)
                else:
                    error = (a - b).magnitude
                if not math.isfinite(error) or error > 1e-5:
                    raise SavedGeometryError(
                        f"Saved coordinate changed by {error:.9g} m at {role} position {compared + 1}; "
                        "the serialization threshold remains 0.00001 m.", original,
                        coordinate_group=role, coordinate_index=compared + 1,
                        expected_wcs=list(a), reopened_wcs=list(b),
                        difference_m=error if math.isfinite(error) else None, tolerance_m=1e-5)
                maximum = max(maximum, error)
                points += 1
                compared += 1
                if cancel is not None and points % 4096 == 0:
                    cancel.check()
        if before != after:
            normalizations.append({
                "entity_type": original.dxftype(), "handle": str(handle),
                "expected_representation": before, "reopened_representation": after,
                "semantic_geometry_verified": True,
                **({"closure_checks": closure_checks} if closure_checks else {}),
            })
        entities += 1
    return {"compared_entities": entities, "compared_coordinates": points,
            "maximum_difference_m": maximum, "tolerance_m": 1e-5,
            "unchecked_entity_types": dict(unchecked),
            "serialization_normalizations": normalizations,
            "scope": "Semantic native positions and checked topology; inactive text alignment tags "
                     "and neutral closing points within the metric publication tolerance are "
                     "normalized for comparison only; every other vertex remains checked. "
                     "Opaque payloads and complete styling are not certified."}


def verify_dxf(path: Path, *, expected_document: Any = None,
               target_crs: Any = None, cancel: CancellationToken | None = None,
               progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Reopen and audit a completed DXF before it is published."""
    notify = progress or (lambda _v, _m: None)
    if cancel is not None:
        cancel.check()
    notify(0.0, "Reopening output DXF")
    try:
        document = ezdxf.readfile(str(path))
        notify(0.3, "Auditing reopened output")
        auditor = document.audit()
    except Exception as exc:
        raise ConversionError(
            f"Output verification could not reopen the DXF: {exc}"
        ) from exc
    errors = len(getattr(auditor, "errors", []) or [])
    if errors:
        raise ConversionError(f"Output verification found {errors} DXF audit error(s).")
    if cancel is not None:
        cancel.check()
    notify(0.5, "Checking output geometry and saved view")
    result = {
        "reopened": True,
        "audit_errors": errors,
        "audit_fixes": len(getattr(auditor, "fixes", []) or []),
        "modelspace_entities": len(document.modelspace()),
        "dxf_version": document.dxfversion,
        "geometry": _modelspace_summary(document, cancel),
        "saved_view": _saved_model_view(document),
    }

    if expected_document is not None and target_crs is not None:
        try:
            result["coordinate_comparison"] = _verify_saved_coordinates(
                expected_document, document, target_crs, cancel,
                lambda v, m: notify(0.65 + 0.34 * v, m))
        except SavedGeometryError as exc:
            failure = exc.verification_failure
            if failure.get("entity_type") in {"HATCH", "MPOLYGON"}:
                geod = target_crs.get_geod() if target_crs.is_geographic else None
                failure["target_crs"] = target_crs.to_string()
                for key, drawing in (("expected_hatch", expected_document),
                                     ("reopened_hatch", document)):
                    entity = drawing.entitydb.get(failure.get("handle", ""))
                    if entity is not None and entity.is_alive and hasattr(entity, "paths"):
                        try:
                            failure[key] = _saved_hatch_snapshot(entity, geod)
                        except Exception as evidence_error:
                            # Diagnostics must never replace the original failure.
                            failure[key] = {"snapshot_error": str(evidence_error)}
            raise
    notify(1.0, "Output verification complete")
    return result


def _validate_output_verification(result: FileResult, verification: dict[str, Any]) -> None:
    """Require surviving finite geometry and the intended startup camera on reopen."""
    result.output_verification = verification
    before = result.display_setup.get("geometry", {})
    after = verification["geometry"]
    if before.get("bounded_entity_count", 0) and not after["bounded_entity_count"]:
        raise ConversionError(
            "Output verification found entity records but no finite display geometry. "
            "No drawing was published."
        )
    if before.get("visible_bounded_entity_count", 0) and not after["visible_bounded_entity_count"]:
        raise ConversionError(
            "All previously visible model-space geometry became hidden after saving. "
            "No drawing was published."
        )
    view = verification["saved_view"]
    if (view["tilemode"] != 1 or view["active_model_viewport_count"] != 1
            or view["height"] is None or not math.isfinite(view["height"])
            or view["height"] <= 0 or view["aspect_ratio"] is None
            or not math.isfinite(view["aspect_ratio"]) or view["aspect_ratio"] <= 0):
        raise ConversionError("The saved output does not have a valid model-space startup view.")
    direction, target = Vec3(view["direction"]), Vec3(view["target"])
    if (not all(math.isfinite(v) for p in (direction, target) for v in p)
            or direction.magnitude == 0
            or not direction.normalize().isclose(Vec3(0, 0, 1), rel_tol=0.0, abs_tol=1e-10)
            or not math.isfinite(view["view_twist"])
            or abs(math.remainder(view["view_twist"], 360)) > 1e-10
            or view["view_mode"] & 7):
        raise ConversionError(
            "The saved output camera is not the unclipped WCS/top view prepared by the converter."
        )
    bounds = after["visible_bounds"] or after["bounds"]
    if bounds:
        low, high = bounds["minimum"], bounds["maximum"]
        cx, cy = view["center"][:2]
        # Top-view DCS coordinates are relative to the WCS view target.
        # CAD writers may move that target without changing the actual view.
        cx, cy = cx + target.x, cy + target.y
        hx, hy = view["height"] * view["aspect_ratio"] / 2, view["height"] / 2
        # Includes only round-off slack, not a metre-sized tolerance in degrees.
        eps = max(view["height"] * 1e-8,
                  64 * math.ulp(max(1.0, abs(cx), abs(cy))))
        if not all(math.isfinite(v) for v in (cx, cy, hx, hy)) or (
                cx - hx > low[0] + eps or cx + hx < high[0] - eps
                or cy - hy > low[1] + eps or cy + hy < high[1] - eps):
            raise ConversionError(
                "The saved startup view does not cover the verified target XY geometry. "
                "No drawing was published; see output verification in the log/report."
            )
    expected_height = result.display_setup.get("saved_view", {}).get("height")
    if expected_height and view["height"] > expected_height * 16:
        raise ConversionError(
            "The reopened view is over 16 times wider in scale than the prepared "
            "target-coordinate view; geometry could appear as an invisible speck. "
            "No drawing was published."
        )
    verification["finite_geometry_verified"] = bool(after["bounded_entity_count"])
    verification["startup_view_fits_xy"] = True


def convert_one_file(
    source: Path,
    job: ConversionJob,
    cancel: CancellationToken,
    log: LogCallback,
    progress: ProgressCallback | None = None,
) -> tuple[FileResult, dict[str, Any]]:
    target = _safe_output_path(source, job)
    result = FileResult(input_path=str(source.resolve()))
    notify = progress or (lambda _v, _m: None)
    started = time.perf_counter()
    phase_start, phase_name = started, "prepare_input"

    def phase(value: float, name: str, message: str) -> None:
        nonlocal phase_start, phase_name
        now = time.perf_counter()
        result.timings_seconds[phase_name] = result.timings_seconds.get(phase_name, 0.0) + now - phase_start
        phase_start, phase_name = now, name
        cancel.check()
        notify(value, message)
        log(message)

    notify(0.0, "Preparing input / ODA DWG-to-DXF" if source.suffix.lower() == ".dwg" else "Preparing input")
    try:
        with prepared_dxf_input(source, job, cancel, log) as dxf_input:
            phase(0.08, "read_and_audit", "Reading and auditing source DXF")
            document, audit = load_dxf(dxf_input, job.audit_and_recover, log)
            phase(0.16, "select_operation", "Checking source extents, CRS operation and mandatory grids")
            engine = DrawingReprojector(document, job, result, cancel, log,
                                        lambda v, m: notify(0.22 + 0.50 * v, m))
            phase(0.22, "reproject_and_view", "Reprojecting model-space geometry")
            engine.run()
            if result.unresolved and job.strict_unresolved:
                summary = ", ".join(
                    f"{key}: {value}" for key, value in result.unresolved.items()
                )
                first_issue = next(
                    (issue for issue in result.issues if issue.severity == "error"),
                    None,
                )
                details = (
                    f" First issue: {first_issue.entity_type} (handle {first_issue.handle}): "
                    f"{first_issue.message}"
                    if first_issue is not None
                    else ""
                )
                raise ConversionError(
                    "Strict mode stopped the conversion because some objects could not be "
                    f"reprojected. No output was published. Unresolved objects: {summary}."
                    + details
                )
            with tempfile.TemporaryDirectory(prefix="cad_epsg_write_") as temp_dir:
                intermediate = Path(temp_dir) / f"{source.stem}.dxf"
                phase(0.73, "write_dxf", "Writing reprojected DXF")
                document.saveas(str(intermediate))
                phase(0.80, "verify_dxf", "Verifying saved DXF coordinates and startup view")
                verification = verify_dxf(intermediate, expected_document=document,
                                          target_crs=engine.target_crs, cancel=cancel,
                                          progress=lambda v, m: notify(0.80 + 0.06 * v, m))
                _validate_output_verification(result, verification)
                if verification["modelspace_entities"] != result.output_entity_count:
                    raise ConversionError(
                        "Output verification found an unexpected model-space entity count: "
                        f"expected {result.output_entity_count}, reopened {verification['modelspace_entities']}."
                    )
                cancel.check()
                if target.suffix.lower() == ".dxf":
                    phase(0.99, "publish", "Publishing verified DXF")
                    _atomic_copy(intermediate, target, job.overwrite)
                else:
                    oda = detect_oda_converter(job.oda_executable)
                    if not oda:
                        raise ConversionError(
                            "DWG output requires ODA File Converter. Choose DXF output or install ODA."
                        )
                    phase(0.87, "oda_dxf_to_dwg", "ODA: converting verified DXF to DWG (external phase)")
                    converted = _oda_convert(
                        intermediate, "dwg", oda, job.dwg_timeout_seconds, cancel
                    )
                    try:
                        # A DWG is verified by an isolated ODA round trip back to DXF.
                        phase(0.92, "oda_roundtrip", "ODA: reopening DWG as DXF for independent file verification")
                        checked_dxf = _oda_convert(
                            converted, "dxf", oda, job.dwg_timeout_seconds, cancel
                        )
                        try:
                            phase(0.96, "verify_dwg", "Verifying DWG round-trip coordinates and startup view")
                            verification = verify_dxf(checked_dxf, expected_document=document,
                                                      target_crs=engine.target_crs, cancel=cancel,
                                                      progress=lambda v, m: notify(0.96 + 0.03 * v, m))
                            _validate_output_verification(result, verification)
                            verification["method"] = "ODA DWG-to-DXF round trip"
                            if (
                                verification["modelspace_entities"]
                                != result.output_entity_count
                            ):
                                raise ConversionError(
                                    "DWG round-trip verification found an unexpected model-space "
                                    f"entity count: expected {result.output_entity_count}, "
                                    f"found {verification['modelspace_entities']}."
                                )
                        finally:
                            shutil.rmtree(checked_dxf.parents[1], ignore_errors=True)
                        cancel.check()
                        phase(0.995, "publish", "Publishing verified DWG")
                        _atomic_copy(converted, target, job.overwrite)
                    finally:
                        shutil.rmtree(converted.parents[1], ignore_errors=True)
        now = time.perf_counter()
        result.timings_seconds[phase_name] = result.timings_seconds.get(phase_name, 0.0) + now - phase_start
        result.timings_seconds["total"] = now - started
        result.output_path = str(target.resolve())
        notify(1.0, f"Verified and published {target.name}")
        metadata = {
            "source_crs": engine.source_crs.to_string(),
            "source_crs_name": engine.source_crs.name,
            "target_crs": engine.target_crs.to_string(),
            "target_crs_name": engine.target_crs.name,
            "operation": engine.operation_description,
            "accuracy_metres": engine.operation_accuracy,
            "best_operation_available": engine.coordinate_operation.best_available,
            "coordinate_operation": engine.coordinate_operation.report(),
            "audit": audit,
            "output_verification": verification,
            "display_setup": result.display_setup,
        }
        return result, metadata
    except ConversionError as exc:
        if isinstance(exc, SavedGeometryError):
            result.output_verification = {
                **result.output_verification,
                "passed": False,
                "stage": phase_name,
                "failure": exc.verification_failure,
            }
        exc.file_result = result.as_json()
        raise
    except Exception as exc:
        reason = str(exc).strip() or type(exc).__name__
        raise ConversionError(reason, file_result=result.as_json()) from exc


def _write_json_report(report: dict[str, Any], path: Path) -> None:
    """Replace a report using a unique temporary file in its output folder."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def convert_job(
    job: ConversionJob,
    cancel: CancellationToken | None = None,
    progress: ProgressCallback | None = None,
    log: LogCallback | None = None,
) -> dict[str, Any]:
    job = validate_job(job)
    network.set_network_enabled(False)
    cancel = cancel or CancellationToken()
    progress = progress or (lambda _value, _message: None)
    log = log or (lambda _message: None)
    source = Path(job.input_paths[0])
    report_path = (
        Path(job.output_directory) / f"{source.stem}_EPSG{job.target_epsg}.json"
    )
    total = len(job.input_paths)
    weights = [max(1, Path(raw).stat().st_size) for raw in job.input_paths]
    weight_sum = sum(weights)
    completed_weight = 0
    last_progress = 0.0
    last_notification = 0.0

    def notify(value: float, message: str) -> None:
        nonlocal last_progress, last_notification
        value = max(last_progress, min(1.0, value))
        now = time.monotonic()
        # Phase changes and terminal events must be visible even for quick files.
        changed = message != getattr(notify, "last_message", "")
        if changed or value >= 1.0 or now - last_notification >= 0.12:
            progress(value, message)
            last_notification = now
            notify.last_message = message
        last_progress = value

    report: dict[str, Any] = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "progress_policy": "Estimated phase/vertex-weighted progress, input-byte-weighted across files; 100% only after report publication. ODA does not expose a true percentage.",
        "started_at_utc": _utc_now(),
        "environment": {
            "python": sys.version.split()[0], "platform": sys.platform,
            "ezdxf": ezdxf.__version__, "pyproj": pyproj.__version__,
            "PROJ": pyproj.proj_version_str,
            "EPSG_database": database.get_database_metadata("EPSG.VERSION"),
            "PROJ_network_enabled": network.is_network_enabled(),
        },
        "finished_at_utc": None,
        "report_path": str(report_path.resolve()),
        "job": asdict(job),
        "operations": [],
        "files": [],
        "omitted_entity_count": 0,
        "drawing_warning_count": 0,
        "auxiliary_cleanup_count": 0,
        "boundary_only_hatch_count": 0,
        "notes": [
            "Curves and bulged polylines are adaptively faceted before nonlinear CRS reprojection.",
            "Block references and dimensions are exploded to transform displayed world geometry.",
            "Proprietary objects that only expose an affine transform receive a local Jacobian transform and are listed in issues.",
            "Raster images, underlays and OLE payloads are not resampled or warped by this application.",
            "By default, unprocessable objects and partial replacements are omitted; their source handles and reasons are listed in issues. The input drawings remain unchanged.",
            "The output opens in model space with a WCS top view fitted to target XY bounds; original layer visibility is preserved.",
            "Polyline widths use local perpendicular scales. Linetypes, positive point sizes and hatch patterns use reported local appearance approximations.",
            "Boundary-only hatches lose their fill; this is reported separately, with original hatch tags archived. Multileaders lose native editing semantics when materialized.",
        ],
    }
    current_input: str | None = None
    try:
        for index, raw in enumerate(job.input_paths):
            source = Path(raw)
            current_input = str(source.resolve())
            cancel.check()
            notify(0.99 * completed_weight / weight_sum,
                   f"Reprojecting {source.name} ({index + 1}/{total})")
            log(f"\n--- {source.name} ---")
            def file_progress(value: float, message: str) -> None:
                notify(0.99 * (completed_weight + weights[index] * value) / weight_sum,
                       f"[{index + 1}/{total}] {source.name} — {message}")
            result, operation = convert_one_file(source, job, cancel, log, file_progress)
            report["files"].append(result.as_json())
            report["omitted_entity_count"] += sum(result.omitted.values())
            report["drawing_warning_count"] += len(result.drawing_warnings)
            report["auxiliary_cleanup_count"] += len(result.auxiliary_coordinate_repairs)
            report["boundary_only_hatch_count"] += sum(
                issue.code == "hatch_boundary_only" for issue in result.issues
            )
            report["operations"].append(operation)
            current_input = None
            completed_weight += weights[index]
            notify(0.99 * completed_weight / weight_sum, f"Completed {source.name}")
        report["status"] = (
            "completed_with_omissions"
            if report["omitted_entity_count"]
            else "completed_with_warnings"
            if report["drawing_warning_count"] or report["boundary_only_hatch_count"]
            else "completed"
        )
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = (
            "cancelled"
            if isinstance(exc, (CancelledError, KeyboardInterrupt))
            else "failed"
        )
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "input_path": current_input,
        }
        if isinstance(exc, ConversionError) and exc.file_result is not None:
            report["failed_file"] = exc.file_result
        raise
    finally:
        report["finished_at_utc"] = _utc_now()
        report["completed_file_count"] = len(report["files"])
        try:
            if report["status"].startswith("completed"):
                notify(0.995, "Writing final conversion report")
            _write_json_report(report, report_path)
        except (OSError, ValueError, TypeError) as exc:
            message = f"Could not write conversion report {report_path}: {exc}"
            if report["status"] in {"completed", "completed_with_omissions", "completed_with_warnings"}:
                raise ConversionError(message) from exc
            # Preserve the original conversion failure if reporting also fails.
            log(message)
    notify(1.0, "Conversion and report completed")
    return report


def inspect_transformation(
    source_epsg: int,
    target_epsg: int,
    allow_ballpark: bool,
    grid_directory: str | None = None,
    *, allow_degraded: bool = False,
) -> str:
    require_dependencies()
    source_epsg, target_epsg = parse_epsg(source_epsg), parse_epsg(target_epsg)
    source = CRS.from_epsg(source_epsg)
    target = CRS.from_epsg(target_epsg)
    operation = build_coordinate_operation(
        source_epsg, target_epsg, allow_ballpark, grid_directory,
        allow_degraded=allow_degraded,
    )
    lines = [
        f"Source: EPSG:{source_epsg} — {source.name}",
        f"Target: EPSG:{target_epsg} — {target.name}",
        f"Method: {'Local NTv2 grids (mandatory)' if operation.grids else 'PROJ operation'}",
        f"Operation: {operation.description}",
    ]
    for grid in operation.grids:
        lines.append(f"Grid: {grid['path']} ({grid['direction']})")
    if operation.grids:
        lines.append(
            "The selected grids correct horizontal coordinates only; they supply no vertical datum correction."
        )
    else:
        accuracy = (
            f"{operation.accuracy:g} m" if operation.accuracy >= 0 else "not stated"
        )
        lines.append(f"PROJ accuracy: {accuracy}")
    for code in dict.fromkeys((source_epsg, target_epsg)):
        if code in SOUTH_WEST_EPSG_CODES:
            lines.append(f"EPSG:{code} axes: CAD X = Southing (P), CAD Y = Westing (M).")
    if not operation.best_available:
        lines.append(
            "A PROJ operation outside the local-grid stages has an unavailable better alternative."
        )
    lines.extend("Note: " + note for note in operation.warnings)
    for detail in operation.stage_details:
        if detail["kind"] == "PROJ":
            lines.append(f"Stage accuracy: {detail['accuracy_metres']} m — {detail['description']}")
    return "\n".join(lines)


def _enable_windows_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        with contextlib.suppress(Exception):
            ctypes.windll.user32.SetProcessDPIAware()


def _monitor_work_area(root: Any) -> tuple[int, int, int, int]:
    root.update_idletasks()
    if os.name == "nt":

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def _gui_column_widths(width: int, scale: float = 1.0) -> tuple[int, int, int]:
    """Keep both main panels visible, including on scaled or narrow desktops."""
    width = max(80, int(width))
    gap = max(8, round(10 * scale))
    available = width - gap
    preferred = max(
        round(420 * scale), min(round(570 * scale), round(available * 0.42))
    )
    left = min(preferred, round(available * 0.52))
    return left, gap, available - left


class ScrollableControls(ttk.Frame if ttk is not None else object):
    """Contained scrolling without allowing child size requests to hide a pane."""

    def __init__(self, master: Any, padding: int = 6) -> None:
        super().__init__(master, width=1, height=1)
        self.grid_propagate(False)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            width=1,
            height=1,
            borderwidth=0,
            highlightthickness=0,
            takefocus=False,
        )
        self.vertical = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.horizontal = ttk.Scrollbar(
            self, orient="horizontal", command=self.canvas.xview
        )
        self.canvas.configure(
            yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vertical.grid(row=0, column=1, sticky="ns")
        self.horizontal.grid(row=1, column=0, sticky="ew")
        self.content = ttk.Frame(self.canvas, padding=padding)
        self.window_item = self.canvas.create_window(
            (0, 0), window=self.content, anchor="nw"
        )
        self.content.bind("<Configure>", self._content_changed)
        self.canvas.bind("<Configure>", self._viewport_changed)
        self._scroll_tag = f"CADScroll_{id(self)}"
        self.bind_class(self._scroll_tag, "<MouseWheel>", self._mouse_wheel)
        self.bind_class(self._scroll_tag, "<Button-4>", self._mouse_wheel)
        self.bind_class(self._scroll_tag, "<Button-5>", self._mouse_wheel)
        self.bind("<Destroy>", self._destroy_bindings, add="+")

    def _content_changed(self, _event: Any = None) -> None:
        width = max(self.canvas.winfo_width(), self.content.winfo_reqwidth(), 1)
        self.canvas.itemconfigure(self.window_item, width=width)
        self.canvas.configure(
            scrollregion=(0, 0, width, max(1, self.content.winfo_reqheight()))
        )

    def _viewport_changed(self, _event: Any = None) -> None:
        self._content_changed()

    def enable_scrolling(self) -> None:
        def visit(widget: Any) -> None:
            # Lists, editors and comboboxes retain their native wheel behavior.
            if widget.winfo_class() not in {"Treeview", "TCombobox", "Text", "Listbox"}:
                tags = widget.bindtags()
                if self._scroll_tag not in tags:
                    widget.bindtags((tags[0], self._scroll_tag, *tags[1:]))
            if widget.winfo_class() in {
                "TEntry",
                "TCombobox",
                "TButton",
                "TCheckbutton",
            }:
                widget.bind("<FocusIn>", self._reveal_focus, add="+")
            for child in widget.winfo_children():
                visit(child)

        visit(self.content)
        self.canvas.bindtags(
            (
                str(self.canvas),
                self._scroll_tag,
                "Canvas",
                str(self.winfo_toplevel()),
                "all",
            )
        )
        self._content_changed()

    def _mouse_wheel(self, event: Any) -> str:
        delta = getattr(event, "delta", 0)
        number = getattr(event, "num", 0)
        steps = (
            -max(1, abs(int(delta)) // 120)
            if delta > 0
            else max(1, abs(int(delta)) // 120)
        )
        if number == 4:
            steps = -1
        elif number == 5:
            steps = 1
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(steps * 2, "units")
        return "break"

    def _reveal_focus(self, event: Any) -> None:
        widget = event.widget
        top = widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        height = self.canvas.winfo_height()
        total = max(1, self.content.winfo_height())
        current = self.canvas.canvasy(0)
        if top < 0:
            self.canvas.yview_moveto(max(0, current + top - 5) / total)
        elif bottom > height:
            self.canvas.yview_moveto(max(0, current + bottom - height + 5) / total)
        left = widget.winfo_rootx() - self.canvas.winfo_rootx()
        right = left + widget.winfo_width()
        viewport_width = self.canvas.winfo_width()
        total_width = max(1, self.content.winfo_width())
        current_x = self.canvas.canvasx(0)
        if left < 0:
            self.canvas.xview_moveto(max(0, current_x + left - 5) / total_width)
        elif right > viewport_width:
            self.canvas.xview_moveto(
                max(0, current_x + right - viewport_width + 5) / total_width
            )

    def _destroy_bindings(self, event: Any) -> None:
        if event.widget is self:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.unbind_class(self._scroll_tag, sequence)


class _PreviewDisplayLimit(RuntimeError):
    """Stop only the lightweight display pipeline, never the conversion."""


def _prepare_cad_preview(
    source: Path,
    job: ConversionJob,
    cancel: CancellationToken,
) -> dict[str, Any]:
    """Render model space through ezdxf without modifying the input drawing.

    Geometry extraction runs on the preview worker. Only plain coordinate lists
    cross into Tk's main thread. Limits apply to visualization exclusively.
    """
    import re

    try:
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.backend import Backend
        from ezdxf.addons.drawing.config import Configuration, ImagePolicy
        from ezdxf.addons.drawing.properties import LayoutProperties
        from ezdxf.path import triangulate
    except (ImportError, OSError) as exc:
        remedy = (
            "Rebuild the executable with Pillow installed and the package "
            "collection options in README.md, including --collect-all PIL."
            if getattr(sys, "frozen", False)
            else "Activate the project's virtual environment and run: "
            'python -m pip install --upgrade "ezdxf==1.4.4" "Pillow>=12.0,<13". '
            "Pillow provides the PIL modules used by the drawing frontend."
        )
        raise ConversionError(
            f"Drawing preview dependencies could not be loaded: {exc}. {remedy}"
        ) from exc

    primitives: list[tuple[str, tuple[float, ...], str, float]] = []
    notices: list[str] = []
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    max_primitives, max_vertices = 35000, 300000
    vertex_count = 0
    skipped_types: dict[str, int] = {}

    def add(kind: str, points: Iterable[Any], properties: Any) -> None:
        nonlocal vertex_count
        cancel.check()
        if len(primitives) >= max_primitives:
            raise _PreviewDisplayLimit(
                f"Display limited to {max_primitives:,} primitives"
            )
        coordinates: list[float] = []
        for point in points:
            if vertex_count >= max_vertices:
                raise _PreviewDisplayLimit(
                    f"Display limited to {max_vertices:,} vertices"
                )
            x, y = float(point[0]), float(point[1])
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            coordinates.extend((x, y))
            vertex_count += 1
        if not coordinates:
            return
        xs, ys = coordinates[0::2], coordinates[1::2]
        bounds[0], bounds[1] = min(bounds[0], min(xs)), min(bounds[1], min(ys))
        bounds[2], bounds[3] = max(bounds[2], max(xs)), max(bounds[3], max(ys))
        color = str(properties.color)[:7]
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            color = "#FFFFFF"
        # ezdxf resolves ACI 7/BYLAYER/BYBLOCK against the black background.
        weight = max(0.8, min(3.0, float(properties.lineweight or 0.25) * 2.0))
        primitives.append((kind, tuple(coordinates), color, weight))

    def flatten(path: Any) -> Iterable[Any]:
        # A display-scale tolerance prevents huge georeferenced curves from
        # producing millions of preview vertices. Conversion has its own policy.
        box = path.bbox()
        span = max(box.size.x, box.size.y) if box.has_data else 1.0
        return path.flattening(distance=max(span / 4000.0, 1e-10), segments=8)

    class VectorBackend(Backend):
        def set_background(self, color: str) -> None:
            pass  # The viewer deliberately uses the CAD black background.

        def draw_point(self, pos: Any, properties: Any) -> None:
            add("point", (pos,), properties)

        def draw_line(self, start: Any, end: Any, properties: Any) -> None:
            add("line", (start, end), properties)

        def draw_path(self, path: Any, properties: Any) -> None:
            for part in path.sub_paths():
                add("line", flatten(part), properties)

        def draw_filled_polygon(self, points: Any, properties: Any) -> None:
            add("fill", points.vertices(), properties)

        def draw_filled_paths(self, paths: Iterable[Any], properties: Any) -> None:
            parts = [part for path in paths for part in path.sub_paths()]
            if not parts:
                return
            # Triangles preserve holes in hatch boundaries and text glyphs;
            # painting holes black would incorrectly cover underlying entities.
            try:
                span = max(max(p.bbox().size.x, p.bbox().size.y) for p in parts)
                for triangle in triangulate(
                    (part.to_path() for part in parts),
                    max_sagitta=max(span / 2500.0, 1e-10),
                    min_segments=4,
                ):
                    add("fill", triangle, properties)
            except (_PreviewDisplayLimit, CancelledError):
                raise
            except Exception:
                if "Some fills shown as outlines" not in notices:
                    notices.append("Some fills shown as outlines")
                for part in parts:
                    add("line", flatten(part), properties)

        def draw_image(self, image_data: Any, properties: Any) -> None:
            boundary = image_data.pixel_boundary_path.clone()
            boundary.transform_inplace(image_data.transform)
            add("line", boundary.vertices(), properties)
            if "Raster images shown as frames" not in notices:
                notices.append("Raster images shown as frames")

        def clear(self) -> None:
            primitives.clear()

    class PreviewFrontend(Frontend):
        def draw_entity(self, entity: Any, properties: Any) -> None:
            cancel.check()
            super().draw_entity(entity, properties)

        def skip_entity(self, entity: Any, msg: str) -> None:
            if msg != "invisible":
                name = entity.dxftype()
                skipped_types[name] = skipped_types.get(name, 0) + 1

        def log_message(self, message: str) -> None:
            if len(notices) < 12 and message not in notices:
                notices.append(message)

    cancel.check()
    with prepared_dxf_input(source, job, cancel, lambda _message: None) as dxf_path:
        document, _audit = load_dxf(
            dxf_path, job.audit_and_recover, lambda _message: None
        )
        cancel.check()
        model = document.modelspace()
        layout_properties = LayoutProperties.from_layout(model)
        layout_properties.set_colors(bg="#000000", fg="#FFFFFF")
        backend = VectorBackend()
        frontend = PreviewFrontend(
            RenderContext(document),
            backend,
            config=Configuration(
                hatching_timeout=2.0,
                image_policy=ImagePolicy.RECT,
                # Keep sub-unit symbols sub-unit: e.g. 1e-5 degree is not 1 degree.
                pdsize=_preview_point_size(document),
            ),
        )
        try:
            frontend.draw_layout(model, layout_properties=layout_properties)
        except _PreviewDisplayLimit as exc:
            notices.append(str(exc))
        if any(entity.dxftype() == "IMAGE" for entity in model):
            notices.append("Raster images shown as frames")
        if skipped_types:
            summary = ", ".join(
                f"{name}: {count}" for name, count in sorted(skipped_types.items())
            )
            notices.append(f"Not displayed: {summary}")
        count = len(model)
    cancel.check()
    return {
        "path": str(source),
        "primitives": primitives,
        "bounds": tuple(bounds) if primitives else None,
        "entities": count,
        "notices": list(dict.fromkeys(notices)),
    }


class CADPreview(ttk.Frame if ttk is not None else object):
    """Interactive black-background CAD view; all Tk calls stay on the UI thread."""

    def __init__(self, master: Any, on_reload: Any = None) -> None:
        super().__init__(master, width=1, height=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.primitives: list[Any] = []
        self.bounds: tuple[float, ...] | None = None
        self.center = (0.0, 0.0)
        self.scale = 1.0
        self._redraw_job: Any = None
        self._paint_job: Any = None
        self._drag: tuple[int, int] | None = None
        self.empty_message = "Open a DXF or DWG drawing to preview it"
        toolbar = ttk.Frame(self, padding=(6, 5))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(2, weight=1)
        ttk.Button(toolbar, text="Fit", command=self.fit, width=5).grid(
            row=0, column=0, sticky="w"
        )
        if on_reload is not None:
            ttk.Button(toolbar, text="Reload", command=on_reload, width=7).grid(
                row=0, column=1, sticky="w", padx=4
            )
        ttk.Label(toolbar, text="Wheel: zoom   •   Drag: pan").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )
        self.canvas = tk.Canvas(
            self,
            width=1,
            height=1,
            background="#000000",
            highlightthickness=0,
            cursor="fleur",
            takefocus=True,
        )
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=5)
        self.summary_var = tk.StringVar(value="Model space • top view")
        self.summary = ttk.Label(
            self,
            textvariable=self.summary_var,
            padding=(6, 5),
            anchor="w",
        )
        self.summary.grid(row=2, column=0, sticky="ew")
        self.canvas.bind("<Configure>", self._resized)
        self.canvas.bind("<ButtonPress-1>", self._pan_start)
        self.canvas.bind("<B1-Motion>", self._pan_move)
        self.canvas.bind(
            "<ButtonRelease-1>", lambda _event: setattr(self, "_drag", None)
        )
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind(
            "<Button-4>", lambda event: self._zoom_at(event.x, event.y, 1.2)
        )
        self.canvas.bind(
            "<Button-5>", lambda event: self._zoom_at(event.x, event.y, 1 / 1.2)
        )
        self.canvas.bind("<Double-Button-1>", lambda _event: self.fit())

    def _resized(self, event: Any) -> None:
        self.summary.configure(wraplength=max(180, event.width - 16))
        self._schedule_redraw()

    def clear(self, message: str = "Open a DXF or DWG drawing to preview it") -> None:
        self.primitives = []
        self.bounds = None
        self.empty_message = message
        self.summary_var.set("Model space • top view")
        self._redraw()

    def set_drawing(self, data: dict[str, Any]) -> None:
        self.primitives = data["primitives"]
        self.bounds = data["bounds"]
        self.empty_message = "No visible model-space geometry was found"
        text = f"{Path(data['path']).name} • {data['entities']:,} model-space objects"
        if data["notices"]:
            text += " • Display notes: " + "; ".join(data["notices"][:3])
        self.summary_var.set(text if len(text) <= 240 else text[:237] + "...")
        self.after_idle(self.fit)

    def fit(self) -> None:
        if self.bounds:
            x1, y1, x2, y2 = self.bounds
            width = max(100, self.canvas.winfo_width())
            height = max(100, self.canvas.winfo_height())
            self.center = ((x1 + x2) / 2, (y1 + y2) / 2)
            span_x, span_y = max(x2 - x1, 1e-9), max(y2 - y1, 1e-9)
            if x1 == x2 and y1 == y2:
                span_x = span_y = 1.0
            self.scale = 0.88 * min(width / span_x, height / span_y)
        self._redraw()

    def _pan_start(self, event: Any) -> None:
        self._drag = (event.x, event.y)
        self.canvas.focus_set()

    def _pan_move(self, event: Any) -> None:
        if self._drag is None:
            return
        dx, dy = event.x - self._drag[0], event.y - self._drag[1]
        self.center = (
            self.center[0] - dx / self.scale,
            self.center[1] + dy / self.scale,
        )
        self._drag = (event.x, event.y)
        self._schedule_redraw()

    def _wheel(self, event: Any) -> str:
        if event.delta:
            self._zoom_at(event.x, event.y, 1.2 if event.delta > 0 else 1 / 1.2)
        return "break"

    def _zoom_at(self, x: float, y: float, factor: float) -> str:
        if not self.bounds:
            return "break"
        half_w, half_h = self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2
        wx = self.center[0] + (x - half_w) / self.scale
        wy = self.center[1] - (y - half_h) / self.scale
        self.scale = max(1e-15, min(1e15, self.scale * factor))
        self.center = (wx - (x - half_w) / self.scale, wy + (y - half_h) / self.scale)
        self._schedule_redraw()
        return "break"

    def _schedule_redraw(self) -> None:
        if self._redraw_job is None:
            self._redraw_job = self.after(35, self._redraw)

    def _redraw(self) -> None:
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
            self._redraw_job = None
        if self._paint_job is not None:
            self.after_cancel(self._paint_job)
            self._paint_job = None
        self.canvas.delete("all")
        if not self.primitives:
            self.canvas.create_text(
                self.canvas.winfo_width() / 2,
                self.canvas.winfo_height() / 2,
                text=self.empty_message,
                fill="#D8E2EE",
                font=("Segoe UI", 12),
                width=max(180, self.canvas.winfo_width() - 40),
                justify="center",
            )
            return
        # Small batches keep dragging, window resizing and conversion responsive.
        self._paint_batch(0)

    def _paint_batch(self, start: int) -> None:
        self._paint_job = None
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale, cx, cy = self.scale, self.center[0], self.center[1]
        end = min(start + 450, len(self.primitives))
        for kind, values, color, weight in self.primitives[start:end]:
            coords: list[float] = []
            for index in range(0, len(values), 2):
                coords.extend(
                    (
                        width / 2 + (values[index] - cx) * scale,
                        height / 2 - (values[index + 1] - cy) * scale,
                    )
                )
            xs, ys = coords[0::2], coords[1::2]
            if (
                max(xs) < -5
                or min(xs) > width + 5
                or max(ys) < -5
                or min(ys) > height + 5
            ):
                continue
            # Tk has bounded integer raster coordinates at extreme zoom levels.
            coords = [max(-1e8, min(1e8, value)) for value in coords]
            if kind == "point" or len(coords) == 2:
                x, y = coords[:2]
                self.canvas.create_oval(
                    x - 2, y - 2, x + 2, y + 2, fill=color, outline=""
                )
            elif kind == "fill" and len(coords) >= 6:
                self.canvas.create_polygon(coords, fill=color, outline="")
            else:
                self.canvas.create_line(coords, fill=color, width=weight)
        if end < len(self.primitives):
            self._paint_job = self.after(1, self._paint_batch, end)


class ProgressEstimator:
    """Elapsed time and a revisable local finish datetime, never a promised deadline.

    Progress is weighted work, not wall-clock percentage. External ODA, DXF reads
    and audits expose no internal count; the elapsed clock remains live while
    those phases hold their completed-work percentage.
    """

    def __init__(self) -> None:
        self.reset()
        self.state = "ready"

    def reset(self, *, monotonic_now: float | None = None,
              wall_now: datetime | None = None) -> None:
        self.started = time.monotonic() if monotonic_now is None else monotonic_now
        self.wall_started = wall_now or datetime.now().astimezone()
        self.fraction = 0.0
        self.last_advance = self.started
        self.samples: deque[tuple[float, float]] = deque([(self.started, 0.0)], maxlen=24)
        self.state = "running"
        self.finished: float | None = None
        self.wall_finished: datetime | None = None

    def update(self, value: float, *, monotonic_now: float | None = None) -> None:
        if not math.isfinite(value):
            return
        now = time.monotonic() if monotonic_now is None else monotonic_now
        value = max(self.fraction, min(1.0, value))
        if value > self.fraction:
            self.samples.append((now, value))
            self.last_advance = now
        self.fraction = value

    def finish(self, state: str, *, monotonic_now: float | None = None,
               wall_now: datetime | None = None) -> None:
        self.state = state
        self.finished = time.monotonic() if monotonic_now is None else monotonic_now
        self.wall_finished = wall_now or datetime.now().astimezone()
        if state == "completed":
            self.fraction = 1.0

    @staticmethod
    def duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def snapshot(self, *, monotonic_now: float | None = None,
                 wall_now: datetime | None = None) -> dict[str, Any]:
        now = time.monotonic() if monotonic_now is None else monotonic_now
        wall = wall_now or datetime.now().astimezone()
        elapsed = max(0.0, (self.finished if self.finished is not None else now) - self.started)
        remaining = None
        finish = self.wall_finished
        stalled = now - self.last_advance >= 30.0
        if self.state == "running" and elapsed >= 2 and 0.005 <= self.fraction < 1:
            average_rate = self.fraction / elapsed
            recent_rate = average_rate
            first, last = self.samples[0], self.samples[-1]
            if last[0] - first[0] >= 2:
                recent_rate = (last[1] - first[1]) / (last[0] - first[0])
                recent_rate = min(average_rate * 4, max(average_rate / 4, recent_rate))
            rate = average_rate if stalled else 0.7 * average_rate + 0.3 * recent_rate
            remaining = max(0.0, (1 - self.fraction) / max(rate, 1e-15))
            # datetime arithmetic stays bounded for pathological progress inputs.
            remaining = min(remaining, 365 * 86400.0)
            finish = wall + timedelta(seconds=remaining)
        return {"state": self.state, "fraction": self.fraction, "elapsed_seconds": elapsed,
                "remaining_seconds": remaining, "finish_datetime": finish,
                "estimate_stalled": stalled}

    def text(self) -> str:
        view = self.snapshot()
        elapsed = self.duration(view["elapsed_seconds"])
        if self.state == "ready":
            return "Elapsed: 00:00:00   |   Estimated finish: —"
        if self.state != "running":
            stamp = view["finish_datetime"].strftime("%Y-%m-%d %H:%M:%S %Z")
            return f"Elapsed: {elapsed}   |   {self.state.capitalize()}: {stamp}"
        finish = view["finish_datetime"]
        if finish is None:
            return f"Elapsed: {elapsed}   |   Estimated finish: calculating from completed work…"
        stamp = finish.strftime("%Y-%m-%d %H:%M:%S %Z")
        remaining = self.duration(view["remaining_seconds"])
        note = " — revising estimate during current phase" if view["estimate_stalled"] else ""
        return f"Elapsed: {elapsed}   |   Estimated finish: ~{stamp}   |   Remaining: ~{remaining}{note}"


class CADConverterApp:
    FORMAT_LABELS: ClassVar[dict[str, str]] = {
        "DXF (.dxf)": "dxf",
        "DWG (.dwg)": "dwg",
    }

    def __init__(self, root: Any) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.work_area = _monitor_work_area(root)
        _, _, width, height = self.work_area
        self.compact = width <= 1400 or height <= 800
        # Establish the window BEFORE widgets negotiate their requested sizes.
        work_x, work_y, work_w, work_h = self.work_area
        initial_w = min(1420, max(480, work_w - 24))
        initial_h = min(860, max(360, work_h - 68))
        self.initial_size = (initial_w, initial_h)
        self.root.geometry(f"{initial_w}x{initial_h}{work_x + 12:+d}{work_y + 12:+d}")
        self.root.minsize(min(940, initial_w), min(500, initial_h))
        self.ui_scale = max(0.85, min(3.0, self.root.winfo_fpixels("1i") / 96.0))
        self._layout_width = -1
        self.input_paths: list[str] = []
        self.worker: threading.Thread | None = None
        self.cancel_token: CancellationToken | None = None
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.closing = False
        self.preview_cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self.preview_request_id = 0
        self.preview_token: CancellationToken | None = None
        self.preview_requests: queue.Queue[Any] = queue.Queue()
        self.preview_worker: threading.Thread | None = None
        self.preview_path: str | None = None
        self._format_input_path: str | None = None

        self.output_var = tk.StringVar()
        self.source_var = tk.StringVar(value=self._label_for(DEFAULT_SOURCE_EPSG))
        self.target_var = tk.StringVar(value=self._label_for(DEFAULT_TARGET_EPSG))
        self.format_var = tk.StringVar(value="DXF (.dxf)")
        self.suffix_var = tk.StringVar(value=f"_EPSG{DEFAULT_TARGET_EPSG}")
        self.tolerance_var = tk.StringVar(value=str(DEFAULT_CURVE_TOLERANCE))
        self.preserve_z_var = tk.BooleanVar(value=True)
        self.paper_var = tk.BooleanVar(value=False)
        self.strict_var = tk.BooleanVar(value=False)
        self.skip_grid_var = tk.BooleanVar(value=True)
        self.ballpark_var = tk.BooleanVar(value=False)
        self.degraded_var = tk.BooleanVar(value=False)
        self.reprojection_var = tk.StringVar(value=str(DEFAULT_REPROJECTION_TOLERANCE_M))
        self.audit_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.oda_var = tk.StringVar()
        self.grid_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.percent_var = tk.StringVar(value="0.0%")
        self.timing_var = tk.StringVar(value="Elapsed: 00:00:00   |   Estimated finish: —")
        self.progress_estimator = ProgressEstimator()
        self._last_timing_refresh = 0.0

        self._configure_style()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._poll_events)
        self._log(f"{APP_NAME} {APP_VERSION}")
        if EZDXF_IMPORT_ERROR or PYPROJ_IMPORT_ERROR:
            self._log(
                "Missing dependencies. Open Advanced / Requirements for installation instructions."
            )
        oda = detect_oda_converter(None)
        self._log(
            f"ODA File Converter: {oda or 'not detected; DXF-to-DXF remains available'}"
        )

    @staticmethod
    def _label_for(code: int) -> str:
        return f"EPSG:{code} — {EPSG_NAME_BY_CODE[code]}"

    def _configure_style(self) -> None:
        from tkinter import font as tkfont

        self.base_font_size = 11 if self.compact else 12
        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ):
            with contextlib.suppress(tk.TclError):
                tkfont.nametofont(name, root=self.root).configure(
                    family="Segoe UI",
                    size=self.base_font_size,
                )
        with contextlib.suppress(tk.TclError):
            tkfont.nametofont("TkFixedFont", root=self.root).configure(
                family="Consolas", size=11
            )
        self.root.option_add("*Font", ("Segoe UI", self.base_font_size))
        self.root.option_add(
            "*TCombobox*Listbox.font", ("Segoe UI", self.base_font_size)
        )
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Segoe UI", self.base_font_size))
        style.configure(
            "Treeview",
            font=("Segoe UI", self.base_font_size),
            rowheight=int(tkfont.nametofont("TkDefaultFont").metrics("linespace") + 7),
        )
        style.configure(
            "Treeview.Heading", font=("Segoe UI", self.base_font_size, "bold")
        )
        style.configure("TNotebook.Tab", padding=(11, 5))
        style.configure("Header.TFrame", background="#0B2545")
        style.configure(
            "HeaderTitle.TLabel",
            background="#0B2545",
            foreground="white",
            font=("Segoe UI", 18, "bold"),
        )
        style.configure(
            "HeaderSub.TLabel",
            background="#0B2545",
            foreground="#CFDCEB",
            font=("Segoe UI", 11),
        )
        style.configure(
            "Primary.TButton",
            font=("Segoe UI", self.base_font_size, "bold"),
            padding=(12, 6),
        )
        style.configure(
            "TLabelframe.Label", font=("Segoe UI", self.base_font_size, "bold")
        )

    def _build_ui(self) -> None:
        pad = 6 if self.compact else 10
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=0)
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(14, 7))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="CAD EPSG Converter", style="HeaderTitle.TLabel").pack(
            anchor="w"
        )
        subtitle = ttk.Label(
            header,
            text="High-fidelity DXF/DWG coordinate reprojection • detailed object audit",
            style="HeaderSub.TLabel",
            justify="left",
        )
        subtitle.pack(anchor="w")
        header.bind(
            "<Configure>",
            lambda event: subtitle.configure(wraplength=max(200, event.width - 28)),
        )

        # A non-collapsible grid reserves both panels. Notebook/Text defaults
        # cannot steal the left column, even during startup or restoration.
        self.body = body = ttk.Frame(self.root, width=1, height=1)
        body.grid(row=1, column=0, sticky="nsew", padx=pad, pady=pad)
        body.grid_propagate(False)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(2, weight=1)
        self.controls_panel = ScrollableControls(body, padding=2)
        self.controls_panel.grid(row=0, column=0, sticky="nsew")
        controls = self.controls_panel.content
        self.right_panel = right = ttk.Frame(body, width=1, height=1)
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_propagate(False)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        body.bind("<Configure>", self._resize_main_panels)
        self._resize_main_panels(width=max(80, self.initial_size[0] - pad * 2))

        self.input_box = input_box = ttk.LabelFrame(
            controls, text="1. Input CAD drawings", padding=7
        )
        input_box.pack(fill="x", pady=(0, 6))
        buttons = ttk.Frame(input_box)
        buttons.pack(fill="x", pady=(0, 5))
        buttons.columnconfigure(0, weight=1)
        self.add_button = ttk.Button(
            buttons, text="Open DXF / DWG…", command=self._add_files
        )
        self.add_button.grid(row=0, column=0, sticky="w")
        self.remove_button = ttk.Button(
            buttons, text="Remove", command=self._remove_files
        )
        self.remove_button.grid(row=0, column=1, padx=5)
        self.clear_button = ttk.Button(buttons, text="Clear", command=self._clear_files)
        self.clear_button.grid(row=0, column=2)
        file_host = ttk.Frame(input_box)
        file_host.pack(fill="x")
        file_host.columnconfigure(0, weight=1)
        self.file_tree = ttk.Treeview(
            file_host,
            columns=("file", "format", "size"),
            show="headings",
            height=3 if self.compact else 4,
            selectmode="extended",
        )
        for key, title, width in (
            ("file", "File", 245),
            ("format", "Type", 58),
            ("size", "Size", 76),
        ):
            self.file_tree.heading(key, text=title)
            self.file_tree.column(key, width=width, stretch=key == "file")
        tree_scroll = ttk.Scrollbar(
            file_host, orient="vertical", command=self.file_tree.yview
        )
        self.file_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.file_tree.grid(row=0, column=0, sticky="ew")
        self.file_tree.bind("<<TreeviewSelect>>", self._file_selected)

        self.crs_box = crs_box = ttk.LabelFrame(
            controls, text="2. Coordinate reference systems", padding=7
        )
        crs_box.pack(fill="x", pady=(0, 6))
        crs_box.columnconfigure(0, weight=1)
        ttk.Label(crs_box, text="Source EPSG").grid(row=0, column=0, sticky="w", pady=3)
        self.source_combo = ttk.Combobox(
            crs_box, textvariable=self.source_var, values=EPSG_LABELS, state="readonly"
        )
        self.source_combo.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.source_combo.bind("<<ComboboxSelected>>", self._source_changed)
        ttk.Label(crs_box, text="Target EPSG").grid(row=2, column=0, sticky="w", pady=3)
        self.target_combo = ttk.Combobox(
            crs_box, textvariable=self.target_var, values=EPSG_LABELS, state="readonly"
        )
        self.target_combo.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        self.target_combo.bind("<<ComboboxSelected>>", self._target_changed)
        self.validate_button = ttk.Button(
            crs_box, text="Validate transformation", command=self._validate_crs
        )
        self.validate_button.grid(row=4, column=0, sticky="e", pady=(2, 1))

        self.output_box = output_box = ttk.LabelFrame(
            controls, text="3. Output", padding=7
        )
        output_box.pack(fill="x")
        output_box.columnconfigure(1, weight=1)
        ttk.Label(output_box, text="Folder").grid(row=0, column=0, sticky="w", pady=3)
        self.output_entry = ttk.Entry(
            output_box, textvariable=self.output_var, width=12
        )
        self.output_entry.grid(row=0, column=1, sticky="ew", padx=7)
        self.folder_button = ttk.Button(
            output_box, text="Browse…", command=self._choose_output
        )
        self.folder_button.grid(row=0, column=2)
        ttk.Label(output_box, text="Format").grid(row=1, column=0, sticky="w", pady=3)
        self.format_combo = ttk.Combobox(
            output_box,
            textvariable=self.format_var,
            values=tuple(self.FORMAT_LABELS),
            state="readonly",
        )
        self.format_combo.grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=7, pady=3
        )
        ttk.Label(output_box, text="Suffix").grid(row=2, column=0, sticky="w", pady=3)
        self.suffix_entry = ttk.Entry(
            output_box, textvariable=self.suffix_var, width=12
        )
        self.suffix_entry.grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=7, pady=3
        )
        ttk.Label(
            output_box, text="Output format applies to all listed drawings."
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        notebook = ttk.Notebook(right)
        self.notebook = notebook
        notebook.grid(row=0, column=0, sticky="nsew")
        self.preview = CADPreview(notebook, on_reload=self._reload_preview)
        notebook.add(self.preview, text="Preview")
        log_tab = ttk.Frame(notebook, padding=5)
        notes_tab = ttk.Frame(notebook, padding=5)
        notebook.add(log_tab, text="Log")
        notebook.add(notes_tab, text="Method / help")
        self.log_text = ScrolledText(
            log_tab,
            width=1,
            height=1,
            wrap="word",
            font=("Consolas", 11),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)
        notes = (
            "Precision policy\n\n"
            "Lines, points, faces and vertices are transformed coordinate by coordinate. "
            "Curves and bulged polylines are converted to dense polylines using the selected "
            "source chord error before reprojection; straight edges are also adaptively refined "
            "against the target metric chord criterion. Block references and dimensions are "
            "exploded so their displayed geometry is transformed in world coordinates.\n\n"
            "CAD objects that expose only an affine transform, including some proprietary or "
            "application-defined entities, are preserved and transformed with the local CRS "
            "Jacobian at their anchor. Every such case is listed in the JSON report. Strict "
            "mode prevents an output from being published if an entity cannot be transformed.\n\n"
            "Out-of-grid cleanup is enabled by default. An object that reaches outside a "
            "mandatory grid is skipped as a complete leaf and reported by handle; other "
            "objects continue. This includes stale origins outside the domain, but in-coverage "
            "origins are retained. Strict mode overrides cleanup. No extrapolation, clamping "
            "or approximate datum fallback is introduced.\n\n"
            "A general CRS conversion is nonlinear. Therefore one shared block definition, a "
            "perfect CAD circle, a hatch pattern or a raster image cannot remain both unchanged "
            "as an object and geographically exact everywhere. Raster and OLE payloads are not "
            "resampled by this program. Always compare the output with surveyed control points."
        )
        notes += (
            "\n\nDrawing preview\n\n"
            "The black-background view displays the original drawing in model space, "
            "from above. It follows layer visibility, CAD colours, blocks, curves, text "
            "and hatch boundaries through ezdxf's drawing renderer. Raster images appear "
            "as frames. A bounded display pipeline keeps the window responsive; display "
            "limits and unsupported objects are shown below the canvas and in the log. "
            "These display limits never affect conversion.\n\n"
            "Portuguese NTv2 grids\n\n"
            "Place pt73_e89.gsb, ptLX_e89.gsb, ptED_e89.gsb and ptLB_e89.gsb beside "
            "this script or executable, or select their folder in Advanced settings. "
            "Validate transformation shows the selected operation and required grids."
            "\n\nOutput display\n\n"
            "The output opens in model space, WCS/top view, fitted to target XY extents. "
            "Z elevations do not control the zoom height. Existing layer visibility is preserved. "
            "Paper-space views and saved named views are not automatically refitted. "
            "Across different horizontal CRSs, widths and display distances use reported local "
            "horizontal scales. Multileaders become native display primitives. Hatches that "
            "cannot remain horizontal fills are retained as 3D boundaries only in best-effort "
            "mode; their missing fills are reported explicitly. Strict mode rejects that fallback. "
            "The JSON report records geometric bounds and the saved view after reopening."
        )
        notes += (
            f"\n\nCRS catalogue ({len(EPSG_SYSTEMS)} unique systems)\n\n"
            "Both selectors follow Global/Web, Mainland Portugal, Azores and Madeira. "
            "PTRA08 geographic 2D (5013), geographic 3D (5012) and geocentric (5011) "
            "apply to both archipelagos. Both Bonne CRSs (2963 "
            "and 5017) use X=southing and Y=westing. ETRS89 / UTM 28N (25828) "
            "is not an alias for PTRA08 / UTM 28N (5016). The required datum grids "
            "and operation-accuracy checks still apply to every selected pair."
        )
        notes_text = ScrolledText(
            notes_tab,
            width=1,
            height=1,
            wrap="word",
            font=("Segoe UI", self.base_font_size),
        )
        notes_text.insert("1.0", notes)
        notes_text.configure(state="disabled")
        notes_text.pack(fill="both", expand=True)
        notebook.select(self.preview)

        self.footer = footer = ttk.Frame(self.root, padding=(pad, 0, pad, pad))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, variable=self.progress_var, maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.percent_label = ttk.Label(footer, textvariable=self.percent_var, anchor="e", width=8)
        self.percent_label.grid(row=0, column=1, sticky="e", pady=(0, 5))
        self.timing_label = ttk.Label(footer, textvariable=self.timing_var, anchor="w", width=1)
        self.timing_label.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.timing_label.bind("<Configure>", lambda event: self.timing_label.configure(
            wraplength=max(240, event.width - 12)))
        self.status_label = ttk.Label(
            footer, textvariable=self.status_var, width=1, anchor="w"
        )
        self.status_label.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        actions = ttk.Frame(footer)
        actions.grid(row=1, column=1, sticky="e")
        self.help_button = ttk.Button(actions, text="Advanced…", command=self._advanced)
        self.help_button.grid(row=0, column=2)
        self.cancel_button = ttk.Button(
            actions, text="Cancel", command=self._cancel, state="disabled"
        )
        self.cancel_button.grid(row=0, column=1, padx=5)
        self.convert_button = ttk.Button(
            actions,
            text="Convert drawings",
            style="Primary.TButton",
            command=self._convert,
        )
        self.convert_button.grid(row=0, column=0)

        self.busy_widgets = [
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.source_combo,
            self.target_combo,
            self.folder_button,
            self.format_combo,
            self.convert_button,
            self.help_button,
            self.validate_button,
            self.output_entry,
            self.suffix_entry,
        ]
        self.controls_panel.enable_scrolling()

    def _resize_main_panels(
        self, event: Any = None, *, width: int | None = None
    ) -> None:
        if event is not None and event.widget is not self.body:
            return
        available = int(width if width is not None else event.width)
        if available < 80 or available == self._layout_width:
            return
        self._layout_width = available
        left, gap, right = _gui_column_widths(available, self.ui_scale)
        self.controls_panel.configure(width=left)
        self.right_panel.configure(width=right)
        self.body.columnconfigure(0, minsize=left, weight=0)
        self.body.columnconfigure(1, minsize=gap, weight=0)
        self.body.columnconfigure(2, minsize=right, weight=1)

    def _log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", str(message).rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Choose CAD drawings",
            filetypes=[
                ("CAD drawings", "*.dxf *.dwg"),
                ("DXF", "*.dxf"),
                ("DWG", "*.dwg"),
            ],
        )
        known = {
            os.path.normcase(str(Path(path).resolve())) for path in self.input_paths
        }
        for raw in paths:
            path = Path(raw).resolve()
            key = os.path.normcase(str(path))
            if key in known:
                continue
            known.add(key)
            self.input_paths.append(str(path))
        if paths and not self.output_var.get() and self.input_paths:
            self.output_var.set(str(Path(self.input_paths[0]).parent))
        self._refresh_files()
        if paths:
            selected = str(Path(paths[-1]).resolve())
            if selected in self.input_paths:
                item = str(self.input_paths.index(selected))
                self.file_tree.selection_set(item)
                self.file_tree.see(item)
                self._autoselect_output_format(selected, force=True)
                self._request_preview(selected)

    def _remove_files(self) -> None:
        indices = sorted(
            (int(item) for item in self.file_tree.selection()), reverse=True
        )
        for index in indices:
            if 0 <= index < len(self.input_paths):
                self.input_paths.pop(index)
        self._refresh_files()
        if self.input_paths:
            self.file_tree.selection_set("0")
            self._autoselect_output_format(self.input_paths[0])
            self._request_preview(self.input_paths[0])
        else:
            self._format_input_path = None
            self.format_var.set("DXF (.dxf)")
            self._clear_preview()

    def _clear_files(self) -> None:
        self.input_paths.clear()
        self._format_input_path = None
        self.format_var.set("DXF (.dxf)")
        self._refresh_files()
        self._clear_preview()

    def _refresh_files(self) -> None:
        self.file_tree.delete(*self.file_tree.get_children())
        for index, raw in enumerate(self.input_paths):
            path = Path(raw)
            try:
                size = f"{path.stat().st_size / 1048576:.2f} MB"
            except OSError:
                size = "Missing"
            self.file_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(path.name, path.suffix.upper()[1:], size),
            )

    def _reload_preview(self) -> None:
        path = self.preview_path
        if not path:
            return
        old_key = getattr(self, "_preview_key", None)
        if old_key is not None:
            self.preview_cache.pop(old_key, None)
        self._preview_key = None
        self._request_preview(path)

    def _file_selected(self, _event: Any = None) -> None:
        selected = self.file_tree.selection()
        if not selected:
            return
        try:
            index = int(selected[-1])
            path = self.input_paths[index]
        except (ValueError, IndexError):
            return
        self._autoselect_output_format(path)
        self._request_preview(path)

    def _autoselect_output_format(self, raw: str, *, force: bool = False) -> None:
        """Select a concrete format once per input change, preserving overrides."""
        path = Path(raw)
        key = os.path.normcase(str(path.resolve()))
        if not force and key == self._format_input_path:
            return
        extension = path.suffix.lower().lstrip(".")
        for label, output_format in self.FORMAT_LABELS.items():
            if extension == output_format:
                self.format_var.set(label)
                self._format_input_path = key
                return

    def _clear_preview(self) -> None:
        self.preview_request_id += 1
        self.preview_path = None
        if self.preview_token:
            self.preview_token.cancel()
        while True:
            try:
                self.preview_requests.get_nowait()
            except queue.Empty:
                break
        self.preview.clear()

    def _request_preview(self, raw: str) -> None:
        if self.closing or (self.worker is not None and self.worker.is_alive()):
            return
        source = Path(raw)
        try:
            stat = source.stat()
            key = (
                str(source.resolve()),
                stat.st_size,
                stat.st_mtime_ns,
                self.oda_var.get().strip(),
                self.audit_var.get(),
            )
        except OSError as exc:
            self._clear_preview()
            self.preview.clear(f"Could not open drawing:\n{exc}")
            return
        if self.preview_path == raw and getattr(self, "_preview_key", None) == key:
            return
        self.preview_path = raw
        self._preview_key = key
        self.preview_request_id += 1
        request_id = self.preview_request_id
        if self.preview_token:
            self.preview_token.cancel()
        self.preview_token = CancellationToken()
        self.notebook.select(self.preview)
        while True:
            try:
                self.preview_requests.get_nowait()
            except queue.Empty:
                break
        if key in self.preview_cache:
            self.preview_cache.move_to_end(key)
            self.preview.set_drawing(self.preview_cache[key])
            return
        message = f"Loading {source.name}…"
        if source.suffix.lower() == ".dwg":
            message += "\nPreparing temporary DXF with ODA File Converter"
        self.preview.clear(message)
        # Preview only requires input settings. It must work before an output
        # folder or datum transformation has been configured.
        job = ConversionJob(
            input_paths=(str(source),),
            output_directory=str(source.parent),
            oda_executable=self.oda_var.get().strip() or None,
            audit_and_recover=self.audit_var.get(),
        )
        self.preview_requests.put((request_id, key, source, job, self.preview_token))
        if self.preview_worker is None or not self.preview_worker.is_alive():
            self.preview_worker = threading.Thread(
                target=self._preview_worker_loop,
                name="cad-drawing-preview",
                daemon=True,
            )
            self.preview_worker.start()

    def _preview_worker_loop(self) -> None:
        while True:
            request = self.preview_requests.get()
            if request is None:
                return
            request_id, key, source, job, cancel = request
            try:
                data = _prepare_cad_preview(source, job, cancel)
                cancel.check()
                self.events.put(("preview_done", (request_id, key, data)))
            except CancelledError:
                continue
            except Exception as exc:
                if not cancel.cancelled:
                    self.events.put(("preview_error", (request_id, str(exc))))

    def _stop_preview_worker(self) -> None:
        if self.preview_token:
            self.preview_token.cancel()
        while True:
            try:
                self.preview_requests.get_nowait()
            except queue.Empty:
                break
        self.preview_requests.put(None)

    def _choose_output(self) -> None:
        directory = filedialog.askdirectory(
            parent=self.root, title="Choose output folder"
        )
        if directory:
            self.output_var.set(directory)

    def _target_changed(self, _event: Any = None) -> None:
        with contextlib.suppress(Exception):
            self.suffix_var.set(f"_EPSG{parse_epsg(self.target_var.get())}")

    def _source_changed(self, _event: Any = None) -> None:
        # Keep the projected default at centimetre-level faceting, but avoid a
        # 0.01-degree tolerance when a geographic source CRS is selected.
        with contextlib.suppress(Exception):
            source = CRS.from_epsg(parse_epsg(self.source_var.get()))
            current = self.tolerance_var.get().strip()
            if source.is_geographic and current == str(DEFAULT_CURVE_TOLERANCE):
                self.tolerance_var.set(str(DEFAULT_ANGULAR_CURVE_TOLERANCE))
            elif not source.is_geographic and current == str(DEFAULT_ANGULAR_CURVE_TOLERANCE):
                self.tolerance_var.set(str(DEFAULT_CURVE_TOLERANCE))

    def _validate_crs(self) -> None:
        try:
            text = inspect_transformation(
                parse_epsg(self.source_var.get()),
                parse_epsg(self.target_var.get()),
                self.ballpark_var.get(),
                self.grid_var.get().strip() or None,
                allow_degraded=self.degraded_var.get(),
            )
            messagebox.showinfo("Coordinate transformation", text, parent=self.root)
        except Exception as exc:
            messagebox.showerror(
                "Transformation unavailable", str(exc), parent=self.root
            )

    def _number(self, variable: Any, label: str) -> float:
        try:
            value = float(variable.get().strip())
        except ValueError as exc:
            raise ConversionError(f"{label} must be numeric.") from exc
        if not math.isfinite(value):
            raise ConversionError(f"{label} must be finite.")
        return value

    def _build_job(self) -> ConversionJob:
        return validate_job(
            ConversionJob(
                input_paths=tuple(self.input_paths),
                output_directory=self.output_var.get().strip(),
                source_epsg=parse_epsg(self.source_var.get()),
                target_epsg=parse_epsg(self.target_var.get()),
                output_format=self.FORMAT_LABELS[self.format_var.get()],
                output_suffix=self.suffix_var.get().strip(),
                curve_tolerance=self._number(self.tolerance_var, "Curve tolerance"),
                preserve_z=self.preserve_z_var.get(),
                transform_paper_space=self.paper_var.get(),
                strict_unresolved=self.strict_var.get(),
                skip_outside_grid=self.skip_grid_var.get(),
                allow_ballpark=self.ballpark_var.get(),
                allow_degraded=self.degraded_var.get(),
                reprojection_tolerance_m=self._number(self.reprojection_var, "Reprojection tolerance"),
                overwrite=self.overwrite_var.get(),
                audit_and_recover=self.audit_var.get(),
                oda_executable=self.oda_var.get().strip() or None,
                grid_directory=self.grid_var.get().strip() or None,
            )
        )

    def _convert(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            job = self._build_job()
        except Exception as exc:
            messagebox.showerror("Cannot start conversion", str(exc), parent=self.root)
            return
        self.cancel_token = CancellationToken()
        # Cancel competing preview work; the displayed/cached preview is retained.
        self.preview_request_id += 1
        self._preview_key = None
        if self.preview_token is not None:
            self.preview_token.cancel()
        while True:
            try:
                self.preview_requests.get_nowait()
            except queue.Empty:
                break
        self._set_busy(True)
        self.progress_estimator.reset()
        self.progress_var.set(0)
        self.percent_var.set("0.0%")
        self.timing_var.set(self.progress_estimator.text())
        self.status_var.set("Conversion in progress…")

        def progress(value: float, message: str) -> None:
            self.events.put(("progress", (value, message)))

        def log(message: str) -> None:
            self.events.put(("log", message))

        def target() -> None:
            try:
                report = convert_job(job, self.cancel_token, progress, log)
                self.events.put(("done", report))
            except CancelledError as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("error", (str(exc), traceback.format_exc())))

        self.worker = threading.Thread(
            target=target, name="cad-epsg-conversion", daemon=True
        )
        self.worker.start()

    def _set_busy(self, busy: bool) -> None:
        for widget in self.busy_widgets:
            with contextlib.suppress(Exception):
                if (
                    widget in {self.source_combo, self.target_combo, self.format_combo}
                    and not busy
                ):
                    widget.configure(state="readonly")
                else:
                    widget.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "preview_done":
                    request_id, key, data = payload
                    if request_id == self.preview_request_id and not self.closing:
                        self.preview_cache[key] = data
                        self.preview_cache.move_to_end(key)
                        while len(self.preview_cache) > 3:
                            self.preview_cache.popitem(last=False)
                        self.preview.set_drawing(data)
                        for notice in data["notices"]:
                            self._log(f"Preview only — {notice}")
                elif kind == "preview_error":
                    request_id, message = payload
                    if request_id == self.preview_request_id and not self.closing:
                        self._preview_key = None  # Reselecting can retry a failed read.
                        self.preview.clear("Preview unavailable\n\n" + message)
                        self._log("Preview: " + message)
                elif kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    value, message = payload
                    self.progress_estimator.update(value)
                    self.progress_var.set(self.progress_estimator.fraction * 100)
                    self.percent_var.set(f"{self.progress_estimator.fraction * 100:.1f}%")
                    self.status_var.set(message)
                elif kind == "done":
                    self.progress_estimator.finish("completed")
                    self.timing_var.set(self.progress_estimator.text())
                    self.percent_var.set("100.0%")
                    self.progress_var.set(100)
                    omitted = payload.get("omitted_entity_count", 0)
                    boundary_only = payload.get("boundary_only_hatch_count", 0)
                    drawing_warnings = payload.get("drawing_warning_count", 0)
                    cleanup = payload.get("auxiliary_cleanup_count", 0)
                    output_objects = sum(item["output_entity_count"] for item in payload["files"])
                    has_warning = bool(omitted or boundary_only or drawing_warnings)
                    self.status_var.set(
                        f"Completed — {omitted} object(s) omitted"
                        if omitted
                        else "Completed with drawing warnings"
                        if has_warning else "Conversion completed"
                    )
                    self._log("\nOutputs:")
                    for item in payload["files"]:
                        self._log(f"  {item['output_path']}")
                    self._log(f"Report: {payload['report_path']}")
                    if omitted:
                        self._log(
                            f"Completed with {omitted} omitted object(s). "
                            "See the report for source handles and reasons."
                        )
                    self._set_busy(False)
                    self.cancel_token = None
                    if not self.closing:
                        show_completion = (
                            messagebox.showwarning if has_warning else messagebox.showinfo
                        )
                        detail = (
                            f"\n\n{omitted} object(s) could not be processed and were omitted. "
                            "Their handles and reasons are listed in the report. "
                            "Your input drawings are unchanged."
                            if omitted
                            else ""
                        )
                        if boundary_only:
                            detail += (f"\n\n{boundary_only} hatch(es) were retained as 3D "
                                       "boundaries only; their fills were not retained.")
                        if cleanup:
                            detail += (f"\n\n{cleanup} auxiliary-coordinate cleanup(s) completed; "
                                       "boundary geometry retained. Details are recorded in the report.")
                        if drawing_warnings:
                            detail += f"\n\n{drawing_warnings} drawing/display warning(s): see the report."
                        show_completion(
                            "Conversion complete with omissions"
                            if omitted else "Conversion complete with warnings"
                            if has_warning else "Conversion complete",
                            f"Converted {len(payload['files'])} drawing(s).\n"
                            f"Verified model-space objects: {output_objects:,}.\n"
                            f"Output startup view fitted to target coordinates.{detail}"
                            f"\n\nReport:\n{payload['report_path']}",
                            parent=self.root,
                        )
                elif kind == "cancelled":
                    self.progress_estimator.finish("cancelled")
                    self.timing_var.set(self.progress_estimator.text())
                    self._log(payload)
                    self.status_var.set("Cancelled")
                    self._set_busy(False)
                    self.cancel_token = None
                elif kind == "error":
                    self.progress_estimator.finish("failed")
                    self.timing_var.set(self.progress_estimator.text())
                    message, details = payload
                    self._log(details)
                    self.status_var.set("Conversion failed — see log")
                    self._set_busy(False)
                    self.cancel_token = None
                    if not self.closing:
                        messagebox.showerror(
                            "Conversion failed", message, parent=self.root
                        )
        except queue.Empty:
            pass
        if self.closing and not any(
            worker is not None and worker.is_alive()
            for worker in (self.worker, self.preview_worker)
        ):
            self.root.destroy()
            return
        now = time.monotonic()
        if self.progress_estimator.state == "running" and now - self._last_timing_refresh >= 0.5:
            self.timing_var.set(self.progress_estimator.text())
            self._last_timing_refresh = now
        self.root.after(80, self._poll_events)

    def _cancel(self) -> None:
        if self.cancel_token:
            self.cancel_token.cancel()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("Cancelling safely…")

    def _advanced(self) -> None:
        existing = getattr(self, "advanced_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        dialog = tk.Toplevel(self.root)
        self.advanced_dialog = dialog
        dialog.withdraw()
        dialog.title("Advanced conversion settings")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)
        panel = ScrollableControls(dialog, padding=12)
        panel.grid(row=0, column=0, sticky="nsew")
        frame = panel.content
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="Maximum curve chord error").grid(
            row=0, column=0, sticky="w", pady=4
        )
        ttk.Entry(frame, textvariable=self.tolerance_var, width=14).grid(
            row=1, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(frame, text="source drawing units").grid(row=1, column=1, sticky="w")
        ttk.Label(frame, text="Adaptive reprojection deviation (metres)").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=4
        )
        ttk.Entry(frame, textvariable=self.reprojection_var, width=14).grid(
            row=3, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Label(frame, text="m, including degree targets").grid(row=3, column=1, sticky="w")
        row = 4
        checks = (
            ("Keep Z elevations in horizontal conversions", self.preserve_z_var),
            ("Transform paper-space geometry", self.paper_var),
            ("Skip objects outside mandatory grid coverage", self.skip_grid_var),
            ("Stop if a geometric object cannot be transformed", self.strict_var),
            ("Allow ballpark datum transformations", self.ballpark_var),
            ("Allow lower-accuracy installed operations", self.degraded_var),
            ("Audit and recover damaged DXF", self.audit_var),
            ("Overwrite existing output files", self.overwrite_var),
        )
        for text, variable in checks:
            ttk.Checkbutton(frame, text=text, variable=variable).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=3
            )
            row += 1
        failure_note = ttk.Label(
            frame,
            text="Out-of-grid objects are skipped and reported by default. Strict mode overrides this option. Valid origins and in-coverage geometry are not removed.",
            wraplength=500,
            justify="left",
            foreground="#5E6B7A",
        )
        failure_note.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        row += 1
        ttk.Separator(frame).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
        row += 1
        ttk.Label(frame, text="ODA File Converter executable").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4
        )
        row += 1
        ttk.Entry(frame, textvariable=self.oda_var, width=20).grid(
            row=row, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            frame, text="Browse…", command=lambda: self._choose_oda(dialog)
        ).grid(row=row, column=1)
        row += 1
        oda_note = ttk.Label(
            frame,
            text="Required for DWG input and output. Leave blank for automatic detection.",
            wraplength=500,
            justify="left",
            foreground="#5E6B7A",
        )
        oda_note.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        row += 1
        ttk.Label(frame, text="NTv2 grid folder").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=4
        )
        row += 1
        ttk.Entry(frame, textvariable=self.grid_var, width=20).grid(
            row=row, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            frame, text="Browse…", command=lambda: self._choose_grid_folder(dialog)
        ).grid(row=row, column=1)
        row += 1
        grid_note = ttk.Label(
            frame,
            text=(
                "Leave blank to use .gsb files beside the script or executable, "
                "then the grids embedded in the executable."
            ),
            wraplength=500,
            justify="left",
            foreground="#5E6B7A",
        )
        grid_note.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 8))
        panel.canvas.bind(
            "<Configure>",
            lambda event: [
                label.configure(wraplength=max(220, event.width - 30))
                for label in (failure_note, oda_note, grid_note)
            ],
            add="+",
        )
        footer = ttk.Frame(dialog, padding=(12, 8))
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Button(
            footer, text="Requirements", command=lambda: self._requirements(dialog)
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Close", command=dialog.destroy).grid(
            row=0, column=1, sticky="e"
        )
        panel.enable_scrolling()
        work_x, work_y, work_w, work_h = self.work_area
        dialog_w = min(round(700 * self.ui_scale), max(360, work_w - 48))
        dialog_h = min(round(600 * self.ui_scale), max(300, work_h - 80))
        position_x = work_x + max(0, (work_w - dialog_w) // 2)
        position_y = work_y + max(12, (work_h - dialog_h) // 2 - 12)
        dialog.geometry(f"{dialog_w}x{dialog_h}{position_x:+d}{position_y:+d}")
        dialog.minsize(min(420, dialog_w), min(360, dialog_h))
        dialog.deiconify()
        dialog.grab_set()

    def _choose_grid_folder(self, parent: Any) -> None:
        directory = filedialog.askdirectory(
            parent=parent, title="Choose Portuguese NTv2 grid folder"
        )
        if directory:
            self.grid_var.set(directory)

    def _choose_oda(self, parent: Any) -> None:
        path = filedialog.askopenfilename(
            parent=parent,
            title="Choose ODA File Converter",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.oda_var.set(path)

    def _requirements(self, parent: Any = None) -> None:
        text = (
            "Source execution: Python with Tcl/Tk, ezdxf, pyproj and Pillow "
            "(imported as PIL). Pip is the installer; Pillow is required by the preview. "
            "Pip also installs NumPy, FontTools, pyparsing, typing_extensions and certifi.\n\n"
            "See README.md for complete environment "
            "activation, complete installation commands and the one-file build.\n\n"
            "The documented build embeds Python, the GUI runtime, packages and four "
            "NTv2 grids. DXF operation needs no separate Python or grid installation. "
            "Leave the grid folder blank to use embedded grids.\n\n"
            "For source execution, place pt73_e89.gsb, ptLX_e89.gsb, "
            "ptED_e89.gsb and ptLB_e89.gsb beside script.py, or select their folder. "
            "The older pt73_e89.gsb and ptLX_e89.gsb aliases remain supported.\n\n"
            "DWG input, output and preview additionally require ODA File Converter. "
            "ODA is an external application and is not included by the one-file build."
        )
        messagebox.showinfo("Requirements", text, parent=parent or self.root)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(
                "Conversion in progress",
                "Cancel the conversion and close after cleanup?",
                parent=self.root,
            ):
                return
            self.closing = True
            self._stop_preview_worker()
            self._cancel()
            return
        self.closing = True
        self._stop_preview_worker()
        if self.preview_worker and self.preview_worker.is_alive():
            self.status_var.set("Closing preview and cleaning temporary files…")
            return
        self.root.destroy()


def launch_gui() -> int:
    if tk is None:
        print(f"Tkinter is unavailable: {TK_IMPORT_ERROR}", file=sys.stderr)
        return 2
    _enable_windows_dpi_awareness()
    root = tk.Tk()
    root.withdraw()
    CADConverterApp(root)
    root.deiconify()
    if os.name == "nt":
        with contextlib.suppress(Exception):
            root.state("zoomed")
    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproject DXF/DWG drawings between the configured Portuguese EPSG systems."
    )
    parser.add_argument("inputs", nargs="*", help="DXF or DWG input drawings")
    parser.add_argument("--output-dir", help="output folder")
    parser.add_argument("--source-epsg", type=int, default=DEFAULT_SOURCE_EPSG)
    parser.add_argument("--target-epsg", type=int, default=DEFAULT_TARGET_EPSG)
    parser.add_argument(
        "--format",
        choices=("dxf", "dwg"),
        default=None,
        help="batch output format; defaults to the first input's format",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {APP_VERSION}"
    )
    parser.add_argument("--suffix", default=None, help="output filename suffix")
    parser.add_argument("--curve-tolerance", type=float, default=None,
                        help="source sagitta; default 0.01 m or 1e-8 degree for a geographic source")
    parser.add_argument("--reprojection-tolerance-m", type=float,
                        default=DEFAULT_REPROJECTION_TOLERANCE_M,
                        help="adaptive target-chord deviation criterion in metres (default 0.01)")
    parser.add_argument("--allow-degraded", action="store_true",
                        help="explicitly allow an installed lower-accuracy PROJ operation; never bypass mandatory NTv2 grids")
    parser.add_argument("--stop-outside-grid", dest="skip_outside_grid", action="store_false",
                        help="stop on a real grid-domain error instead of skipping the affected object")
    parser.add_argument("--transform-paper-space", action="store_true")
    parser.add_argument("--allow-ballpark", action="store_true")
    failure_policy = parser.add_mutually_exclusive_group()
    failure_policy.add_argument(
        "--strict",
        dest="strict_unresolved",
        action="store_true",
        help="stop publication if an object cannot be transformed",
    )
    failure_policy.add_argument(
        "--allow-unresolved",
        dest="strict_unresolved",
        action="store_false",
        help="omit unprocessable objects and continue (the default)",
    )
    parser.set_defaults(strict_unresolved=False)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--oda", help="ODAFileConverter executable")
    parser.add_argument(
        "--grid-dir", help="NTv2 folder; default: beside script or executable"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.inputs:
        return launch_gui()
    if not arguments.output_dir:
        print("--output-dir is required in command-line mode.", file=sys.stderr)
        return 2
    try:
        require_dependencies()
        source = parse_epsg(arguments.source_epsg)
        target = parse_epsg(arguments.target_epsg)
        curve_tolerance = arguments.curve_tolerance
        if curve_tolerance is None:
            curve_tolerance = default_curve_tolerance(source)
        job = ConversionJob(
            input_paths=tuple(arguments.inputs),
            output_directory=arguments.output_dir,
            source_epsg=source,
            target_epsg=target,
            output_format=arguments.format
            or Path(arguments.inputs[0]).suffix.lower().lstrip("."),
            output_suffix=arguments.suffix
            if arguments.suffix is not None
            else f"_EPSG{target}",
            curve_tolerance=curve_tolerance,
            transform_paper_space=arguments.transform_paper_space,
            strict_unresolved=arguments.strict_unresolved,
            skip_outside_grid=arguments.skip_outside_grid,
            allow_ballpark=arguments.allow_ballpark,
            allow_degraded=arguments.allow_degraded,
            reprojection_tolerance_m=arguments.reprojection_tolerance_m,
            overwrite=arguments.overwrite,
            oda_executable=arguments.oda,
            grid_directory=arguments.grid_dir,
        )
        report = convert_job(
            job,
            progress=lambda value, message: print(f"[{value:6.1%}] {message}"),
            log=print,
        )
        print(f"Report: {report['report_path']}")
        return 0
    except (ConversionError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
