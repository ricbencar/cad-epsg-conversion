#!/usr/bin/env python3
r"""CAD EPSG Converter | Version 1.0 | script.py

Purpose and coordinate theory
-----------------------------
Convert DXF/DWG drawings between the coordinate reference systems in EPSG_SYSTEMS.
The default source is EPSG:27493 (Datum 73 / Modified Portuguese Grid); the
default target is EPSG:3763 (ETRS89 / Portugal TM06). DXF is read and written
with ezdxf. DWG requires the separately installed ODA File Converter.

A projected-to-projected conversion consists of inverse source projection,
datum transformation in geographic coordinates, then forward target projection.
For the supported Portuguese historical datums, the datum transformation uses
the local NTv2 displacement grids, with bilinear interpolation at each point:

    Datum 73     -> ETRS89: pt73_e89.gsb
    ED50         -> ETRS89: ptED_e89.gsb
    Lisbon 1890  -> ETRS89: ptLB_e89.gsb
    Lisbon       -> ETRS89: ptLX_e89.gsb

Reverse transformations use inverse grid shifts. Transformations between these
historical datums pass through ETRS89. Missing, incompatible or out-of-coverage
grids stop conversion; a required local grid is never silently substituted.
Other supported CRS pairs use available PROJ coordinate operations. Ballpark
operations require explicit selection in Advanced settings.

CAD X/Y means easting/northing for normal projected systems and Greenwich
longitude/latitude in degrees for geographic systems. EPSG:2963 follows its
defined south/west axes: CAD X = Southing, CAD Y = Westing. Horizontal grid
shifts do not correct vertical datums. Z is preserved by default for horizontal
conversions; geocentric conversions require valid XYZ coordinates and transform
all three components. Check results against suitable surveyed control points.

Geometry and precision
----------------------
Point-defined geometry is transformed vertex by vertex in world coordinates.
Curves and bulged polylines are faceted using the maximum source-space chord
error selected in Advanced settings (default 0.01 source drawing units for a
projected source). This tolerance controls curve approximation, not geodetic
accuracy or a global target-space error bound. Straight segments join the
transformed vertices. Block references and dimensions are exploded to transform
their displayed geometry; their original editing semantics are not retained.

Objects exposing only an affine transformation use a local Jacobian at an
anchor point and are explicitly recorded as approximations. Unsupported
geometry is recorded as unresolved. Strict mode stops publication of that
drawing if unresolved geometry remains. A failed handler that may have partially
changed an object always stops publication, including in non-strict mode.
Nonlinear reprojection cannot guarantee
exact preservation of every proprietary CAD object, constraint or payload.
Raster images, underlays and OLE contents are not warped. Paper-space geometry
is excluded unless selected. Document tables and non-geometric metadata are
retained where supported by ezdxf/ODA; embedded coordinate-bearing application
data and external reference files are not independently reprojected.

GUI usage
---------
1. When running from source, place the four .gsb files beside script.py.
   The one-file build below embeds these grids in script.exe. Advanced settings
   can select a different grid folder; leave it blank to use bundled resources.
2. Run the script and use Open DXF / DWG in the left input panel. Opening or
   selecting a drawing displays its model space in the black preview on the
   right. Scroll to zoom, drag to pan, and use Fit to show drawing extents.
3. Select source and target EPSG systems, the output folder and output suffix.
   Opening/selecting a drawing selects DWG for DWG input or DXF for DXF input.
   You can then change the output format to either DWG or DXF. The selected
   output format applies to every drawing in the input list. Preview reloads
   do not change a manually selected format.
4. Use Validate transformation to inspect the operation and required grids.
   Set ODA File Converter in Advanced settings if it is not detected.
5. Choose Convert drawings. The default output is <input>_EPSG3763.dxf or .dwg.
   The output folder also receives report_3763.json; other targets use
   report_<target EPSG>.json. The report describes completed files, operations,
   grids, approximations and any batch failure. Each run replaces that report.
   Existing CAD outputs require the explicit overwrite setting. If a batch
   stops, drawings already completed remain in the output folder.

The preview can limit complex drawings for responsiveness. Preview limits never
limit conversion. Conversion works on temporary copies before publishing each
completed drawing and does not modify the input drawings.

Windows installation and virtual environment (Python 3.12, 64-bit)
-----------------------------------------------------------------
Install 64-bit Python 3.12 with pip and Tcl/Tk. Open Windows Command Prompt in
the folder containing script.py. These are shell commands, not statements for
Python's >>> prompt. Python creates the environment; activate.bat activates it
in the current shell. Use python -m pip after activation so installations belong
to that environment. The caret continues a Command Prompt command; put no spaces
after a line-ending caret.

    py -m venv .venv
    call .venv\Scripts\activate.bat
    python -m ensurepip --upgrade
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install --upgrade ^
        "ezdxf==1.4.4" "pyproj==3.7.2" "Pillow>=12.0,<13" ^
        "numpy>=1.26,<3" "fonttools>=4.61,<5" "pyparsing>=3.0,<4" ^
        "typing_extensions>=4.6,<5" certifi
    python -m pip check
    python -c "import sys; assert sys.prefix != sys.base_prefix; print(sys.executable)"
    python -c "import tkinter, ezdxf, pyproj, PIL, numpy, fontTools; from ezdxf.addons.drawing import Frontend, RenderContext; print('Runtime and preview imports passed')"
    python -m tkinter
    python script.py

Close the Tkinter demonstration window before launching script.py. Reactivate
the environment with call .venv\Scripts\activate.bat in each new Command Prompt
opened in the project folder. Run deactivate when finished. Python cannot
activate a parent shell by executing an activation file as a child process.

Package roles:
    pip: package installer; it does not render the drawing preview.
    Pillow (import name PIL): image utilities required by ezdxf's drawing
        frontend, even though this application's preview uses a Tk Canvas.
    ezdxf: CAD documents and drawing frontend.
    pyproj: CRS operations, PROJ binaries and coordinate-system database.
    numpy, fonttools, pyparsing, typing_extensions: ezdxf runtime dependencies.
    certifi: a pyproj runtime dependency.
    setuptools, wheel: packaging support in the build environment.

Pip normally resolves declared transitive dependencies; they are listed above
explicitly for completeness. Pillow must be requested separately with this
installation. Tkinter/Tcl/Tk belongs to the Python installation, not a pip
package. Matplotlib, Qt and PyMuPDF are not required by the custom preview;
installing ezdxf[draw] would add unrelated drawing backends. Core versions are
pinned to the verified API baseline. Other requirements allow compatible
upgrades; capture the resolved versions with pip freeze before distribution.

For DWG input, output or preview, install ODA File Converter on the destination
machine. It is a separate native application, not a pip dependency.

Command-line usage
------------------
    python script.py drawing.dxf --output-dir output
    python script.py drawing.dwg --output-dir output --format dxf
    python script.py drawing.dxf --output-dir output --grid-dir grids
    python script.py --help

Without --format, the first input's extension selects the batch output format.
Use --format dwg or --format dxf to select it explicitly. Source/target defaults
can be set with --source-epsg and --target-epsg. Run without inputs for the GUI.

Syntax compilation and standalone one-file Windows executable
------------------------------------------------------------
py_compile checks syntax and creates bytecode; it does not create an executable.
PyInstaller packages Python, imported modules, native libraries and selected data.
Build on Windows in the activated environment above, with all four correctly
named grid files in the current project folder. Keep this environment limited
to the required packages so optional CAD backends are not collected accidentally.

    python -m py_compile script.py
    python -m pip install --upgrade "PyInstaller>=6.15,<7" pyinstaller-hooks-contrib
    python -m pip check
    python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
        --name script --collect-all ezdxf --collect-all pyproj ^
        --collect-all PIL --collect-all fontTools ^
        --add-data "pt73_e89.gsb:." --add-data "ptLX_e89.gsb:." ^
        --add-data "ptED_e89.gsb:." --add-data "ptLB_e89.gsb:." script.py
    python -m pip freeze --all > build-requirements.txt
    python -c "import pyproj; pyproj.show_versions()" > build-environment.txt

The result is dist\script.exe. Pillow is installed as Pillow but collected as
PIL; fonttools is collected as fontTools. Standard PyInstaller hooks handle
NumPy and Tcl/Tk. The build embeds the four grids and PROJ resources: DXF input,
preview, reprojection and DXF output need no separate Python, pip, Pillow or
grid-file installation on the destination computer. The application still uses
normal operating-system facilities, installed fonts and temporary disk space.
One-file resources are extracted to a temporary directory while the program runs.

DWG support is not self-contained in this executable: ODA remains external.
Neither pip nor --onefile adds a DWG engine. A fully self-contained DWG product
requires a compatible redistributable DWG runtime, separate integration and
Windows validation; the command above does not provide that runtime.

Leave Advanced > NTv2 grid folder blank to use embedded grids. External grids
beside script.exe take priority; an explicitly selected grid folder is exclusive.
For the DGT grids, follow README.md's datum-specific alias instructions before
building. Keep the README and grid attribution with the distribution records.

The --windowed build is for GUI use. Omit --windowed to show CLI help, progress
and errors; retain every collection and --add-data option. Test dist\script.exe
on a clean Windows machine without Python and without external grids, checking
the preview, a known-coordinate conversion and report_3763.json. Check DWG paths
separately with ODA installed. Source checks do not validate a frozen Windows
application; a clean-machine run is required before claiming deployment success.

Build references:
    https://docs.python.org/3/library/venv.html
    https://docs.python.org/3/library/py_compile.html
    https://pillow.readthedocs.io/en/stable/installation/basic-installation.html
    https://ezdxf.readthedocs.io/en/stable/setup.html
    https://pyinstaller.org/en/stable/usage.html
    https://pyinstaller.org/en/stable/hooks.html
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
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

APP_NAME = "CAD EPSG Converter"
APP_VERSION = "1.0"
DEFAULT_SOURCE_EPSG = 27493
DEFAULT_TARGET_EPSG = 3763
DEFAULT_CURVE_TOLERANCE = 0.01
DEFAULT_DWG_TIMEOUT = 900


# Supported CRS identifiers and descriptive labels shown in both selectors.
EPSG_SYSTEMS: tuple[tuple[int, str], ...] = (
    (3763, "ETRS89 / Portugal TM06"),
    (4936, "ETRS89 / Geocentric coordinates"),
    (4937, "ETRS89 / Geographic 3D"),
    (4258, "ETRS89 / Geographic 2D"),
    (4274, "Datum 73 / Geographic 2D"),
    (27493, "Datum 73 / Modified Portuguese Grid"),
    (4207, "Lisbon / Geographic 2D"),
    (5018, "Lisbon / Portuguese Grid New"),
    (20790, "Lisbon / Portuguese National Grid"),
    (5011, "PTRA08 / Geocentric coordinates"),
    (5012, "PTRA08 / Geographic 3D"),
    (5013, "PTRA08 / Geographic 2D"),
    (5014, "PTRA08 / UTM zone 25N - western Azores"),
    (5015, "PTRA08 / UTM zone 26N - central/eastern Azores"),
    (5016, "PTRA08 / UTM zone 28N - Madeira"),
    (2188, "Azores Occidental 1939 / UTM zone 25N"),
    (2189, "Azores Central 1948 / UTM zone 26N"),
    (2190, "Azores Oriental 1940 / UTM zone 26N"),
    (2942, "Porto Santo / UTM zone 28N"),
    (25829, "ETRS89 / UTM zone 29N"),
    (4326, "WGS 84 / Geographic 2D"),
    (3857, "WGS 84 / Pseudo-Mercator"),
    (20791, "Lisbon / Portuguese Grid"),
    (4666, "Lisbon 1890 / Geographic 2D"),
    (2963, "Lisbon 1890 / Portugal Bonne (X=South, Y=West)"),
    (4230, "ED50 / Geographic 2D"),
    (23029, "ED50 / UTM zone 29N"),
)

EPSG_LABELS = tuple(f"EPSG:{code} — {name}" for code, name in EPSG_SYSTEMS)
EPSG_NAME_BY_CODE = dict(EPSG_SYSTEMS)


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
    from pyproj import CRS, Transformer
    from pyproj.transformer import TransformerGroup
except Exception as exc:  # pragma: no cover - shown in the GUI
    CRS = None  # type: ignore[assignment,misc]
    Transformer = None  # type: ignore[assignment]
    TransformerGroup = None  # type: ignore[assignment]
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


class CancelledError(ConversionError):
    """Raised after a cooperative cancellation request."""


class CoordinateTransformationError(ConversionError):
    """A failed datum operation must never be downgraded to a CAD warning."""


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
    curve_tolerance: float = DEFAULT_CURVE_TOLERANCE
    preserve_z: bool = True
    transform_paper_space: bool = False
    strict_unresolved: bool = True
    allow_ballpark: bool = False
    overwrite: bool = False
    audit_and_recover: bool = True
    oda_executable: str | None = None
    dwg_timeout_seconds: int = DEFAULT_DWG_TIMEOUT
    grid_directory: str | None = None


@dataclass
class EntityIssue:
    severity: str
    code: str
    message: str
    layout: str
    entity_type: str
    handle: str


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
    issues: list[EntityIssue] = field(default_factory=list)

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
# The .gsb files supplied by the user are JAG08_01 grids described by Goncalves
# (FCUP, 2009). They are horizontal corrections, not a vertical datum model.
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
    4207: "lisbon",
    5018: "lisbon",
    20790: "lisbon",
    20791: "lisbon",
}


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
    found: dict[str, Path] = {}
    names = [item[1] for item in GRID_FAMILIES.values()]
    for root in grid_search_directories(grid_directory):
        for name in names:
            candidate = root / name
            if name not in found and candidate.is_file():
                found[name] = candidate.resolve()
    return found


def _read_grid_metadata(path: Path, expected_datum: str) -> dict[str, Any]:
    """Verify an NTv2 overview and record the actual file used in the report."""
    try:
        data = path.read_bytes()
        if len(data) < 352 or data[:8] != b"NUM_OREC":
            raise ValueError("not an NTv2 binary grid")
        endian = "<" if struct.unpack("<i", data[8:12])[0] == 11 else ">"
        if struct.unpack(endian + "i", data[8:12])[0] != 11:
            raise ValueError("unsupported NTv2 overview header")
        records = {
            data[i : i + 8].decode("ascii").strip(): data[i + 8 : i + 16]
            for i in range(0, 176, 16)
        }
        source = records["SYSTEM_F"].decode("ascii").strip()
        target = records["SYSTEM_T"].decode("ascii").strip()
        units = records["GS_TYPE"].decode("ascii").strip()
        if source != expected_datum or target != "ETRS89" or units != "SECONDS":
            raise ValueError(
                f"unexpected datum/units: {source} -> {target}, {units}; "
                f"expected {expected_datum} -> ETRS89, SECONDS"
            )
        sub = {
            data[i : i + 8].decode("ascii").strip(): data[i + 8 : i + 16]
            for i in range(176, 352, 16)
        }

        def number(key: str) -> float:
            return struct.unpack(endian + "d", sub[key])[0]

        metadata = {
            "filename": path.name,
            "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "version": records["VERSION"].decode("ascii").strip(),
            "source_datum": source,
            "target_datum": target,
            "horizontal_only": True,
            "first_subgrid_bounds_degrees": {
                "west": -number("W_LONG") / 3600,
                "east": -number("E_LONG") / 3600,
                "south": number("S_LAT") / 3600,
                "north": number("N_LAT") / 3600,
            },
        }
        return metadata
    except (OSError, ValueError, KeyError, struct.error) as exc:
        raise CoordinateTransformationError(
            f"Invalid local grid {path}: {exc}"
        ) from exc


@dataclass
class CoordinateOperation:
    """Scalar coordinate chain with explicit, mandatory NTv2 stages."""

    stages: list[tuple[str, Any]] = field(default_factory=list)
    grids: list[dict[str, Any]] = field(default_factory=list)
    best_available: bool = True
    accuracy: float = 0.0

    @property
    def description(self) -> str:
        return " -> ".join(label for label, _transformer in self.stages)

    @property
    def definition(self) -> str:
        return "\n".join(str(stage.definition) for _label, stage in self.stages)

    def transform(
        self, x: float, y: float, z: float | None = None, errcheck: bool = True
    ) -> tuple[float, ...]:
        values = (float(x), float(y)) if z is None else (float(x), float(y), float(z))
        for label, transformer in self.stages:
            try:
                # Required grids never use @optional, null, or a fallback datum shift.
                values = transformer.transform(*values, errcheck=True)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("non-finite output coordinate")
            except Exception as exc:
                raise CoordinateTransformationError(
                    f"Coordinate transformation failed at {label}: {exc}. "
                    "Check the source EPSG and drawing coordinates. For a local NTv2 grid, "
                    "all transformed locations must lie inside its coverage; no fallback is used."
                ) from exc
        return values

    def report(self) -> dict[str, Any]:
        return {
            "method": "Local NTv2 grid chain"
            if self.grids
            else "PROJ coordinate operation",
            "description": self.description,
            "definition": self.definition,
            "grids": self.grids,
            "best_operation_available": self.best_available,
            "accuracy_metres": None if self.accuracy < 0 else self.accuracy,
            "accuracy_note": (
                "The supplied grid is applied by bilinear interpolation. Its regional residual "
                "statistics do not establish a guaranteed accuracy for every drawing. "
                "No vertical datum correction is supplied by these NTv2 files."
                if self.grids
                else "Accuracy is the value stated by PROJ."
            ),
        }


def build_coordinate_operation(
    source_epsg: int,
    target_epsg: int,
    allow_ballpark: bool = False,
    grid_directory: str | None = None,
) -> CoordinateOperation:
    """Select a grid by datum, normalize longitude, then project the result.

    Greenwich normalization is essential for EPSG:20790 and 20791: their base
    geographic CRS uses the Lisbon prime meridian. A grid is applied only to
    Greenwich longitude/latitude, never directly to projected CAD coordinates.
    """
    require_dependencies()
    source = CRS.from_epsg(source_epsg)
    target = CRS.from_epsg(target_epsg)
    source_family = GRID_FAMILY_BY_EPSG.get(source_epsg)
    target_family = GRID_FAMILY_BY_EPSG.get(target_epsg)
    operation = CoordinateOperation()
    paths = discover_grid_paths(grid_directory)

    def add_projection(a: Any, b: Any) -> None:
        a, b = CRS.from_user_input(a), CRS.from_user_input(b)
        if a.equals(b):
            return

        # EPSG:9828 (Bonne South Orientated) is not implemented by PROJ.
        # For EPSG:2963, zero false offsets + South/West axes reproduce it
        # with ordinary Bonne (9827). Retain BOTH axes and the Lisbon meridian.
        # IOGP GN7-2, section 3.1.4.1: W=-E and S=-N for zero false offsets.
        def supported_bonne(crs: Any) -> Any:
            if crs.to_epsg() != 2963:
                return crs
            definition = crs.to_json_dict()
            definition["conversion"]["method"] = {
                "name": "Bonne",
                "id": {"authority": "EPSG", "code": 9827},
            }
            definition.pop("id", None)
            return CRS.from_json_dict(definition)

        a, b = supported_bonne(a), supported_bonne(b)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            group = TransformerGroup(
                a, b, always_xy=True, allow_ballpark=allow_ballpark
            )
        if not group.transformers:
            raise CoordinateTransformationError(
                f"No installed coordinate operation is available from {a.name} to {b.name}."
            )
        transformer = group.transformers[0]
        operation.stages.append((transformer.description, transformer))
        operation.best_available = operation.best_available and group.best_available
        if operation.accuracy >= 0:
            operation.accuracy = (
                -1.0
                if transformer.accuracy < 0
                else operation.accuracy + transformer.accuracy
            )

    def add_grid(family: str, inverse: bool = False) -> None:
        _geographic, filename, expected = GRID_FAMILIES[family]
        path = paths.get(filename)
        if path is None:
            searched = "; ".join(
                str(root) for root in grid_search_directories(grid_directory)
            )
            raise CoordinateTransformationError(
                f"Required NTv2 grid is missing: {filename}. Put this file beside the script "
                f"or executable, or select its folder in Advanced settings. Searched: {searched}"
            )
        metadata = _read_grid_metadata(path, expected)
        absolute = path.as_posix()
        if any(char in absolute for char in ('"', ",", "\n", "\r")):
            raise CoordinateTransformationError(
                "The NTv2 folder path contains a character unsupported by PROJ grid lists. "
                "Select a folder without commas, quotation marks or line breaks."
            )
        pipeline = (
            "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
            f'+step {"+inv " if inverse else ""}+proj=hgridshift +grids="{absolute}" '
            "+step +proj=unitconvert +xy_in=rad +xy_out=deg"
        )
        try:
            transformer = Transformer.from_pipeline(pipeline)
        except Exception as exc:
            raise CoordinateTransformationError(
                f"Cannot load required NTv2 grid {path}: {exc}"
            ) from exc
        metadata["direction"] = "inverse" if inverse else "forward"
        operation.grids.append(metadata)
        operation.stages.append(
            (f"NTv2 {filename} ({metadata['direction']})", transformer)
        )
        operation.accuracy = -1.0

    if source_family is not None and source_family == target_family:
        # Same datum: projection/meridian conversion only, no correction twice.
        geographic = GRID_FAMILIES[source_family][0]
        add_projection(source, geographic)
        add_projection(geographic, target)
    elif source_family is not None or target_family is not None:
        hub = 4937 if source.is_geocentric or target.is_geocentric else 4258
        if source_family:
            add_projection(source, GRID_FAMILIES[source_family][0])
            add_grid(source_family)
        else:
            add_projection(source, hub)
        if target_family:
            add_grid(target_family, inverse=True)
            add_projection(GRID_FAMILIES[target_family][0], target)
        else:
            add_projection(hub, target)
    else:
        add_projection(source, target)
    return operation


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

    def __init__(
        self,
        document: Any,
        job: ConversionJob,
        result: FileResult,
        cancel: CancellationToken,
        log: LogCallback,
    ) -> None:
        self.doc = document
        self.job = job
        self.result = result
        self.cancel = cancel
        self.log = log
        self.source_crs = CRS.from_epsg(job.source_epsg)
        self.target_crs = CRS.from_epsg(job.target_epsg)
        self.coordinate_operation = build_coordinate_operation(
            job.source_epsg, job.target_epsg, job.allow_ballpark, job.grid_directory
        )
        self.transformer = self.coordinate_operation
        self.use_3d = (
            len(self.source_crs.axis_info) >= 3 or len(self.target_crs.axis_info) >= 3
        )

    @property
    def operation_description(self) -> str:
        return getattr(self.transformer, "description", "coordinate transformation")

    @property
    def operation_accuracy(self) -> float | None:
        accuracy = getattr(self.transformer, "accuracy", None)
        return float(accuracy) if accuracy is not None and accuracy >= 0 else None

    def transform_point(self, value: Any) -> Any:
        x, y, z = _point_tuple(value)
        if self.use_3d:
            tx, ty, tz = self.transformer.transform(x, y, z, errcheck=True)
        else:
            tx, ty = self.transformer.transform(x, y, errcheck=True)
            tz = z if self.job.preserve_z else 0.0
        if not all(math.isfinite(item) for item in (tx, ty, tz)):
            raise ConversionError(
                f"Non-finite transformed coordinate from ({x}, {y}, {z})."
            )
        return Vec3(float(tx), float(ty), float(tz))

    def _local_matrix(self, anchor: Any) -> Any:
        p = Vec3(anchor)
        # A small angular step and a metric step provide stable numerical
        # derivatives without moving far enough for projection curvature to dominate.
        step = (
            1e-5
            if self.source_crs.is_geographic
            else max(1e-3, self.job.curve_tolerance)
        )
        p0 = self.transform_point(p)
        px = self.transform_point(Vec3(p.x + step, p.y, p.z))
        py = self.transform_point(Vec3(p.x, p.y + step, p.z))
        ux = (px - p0) / step
        uy = (py - p0) / step
        if self.use_3d:
            pz = self.transform_point(Vec3(p.x, p.y, p.z + step))
            uz = (pz - p0) / step
        else:
            uz = Vec3(0.0, 0.0, 1.0 if self.job.preserve_z else 0.0)
        if ux.magnitude < 1e-15 or uy.magnitude < 1e-15:
            raise ConversionError(
                "Local CRS derivative is singular at an entity location."
            )
        return Matrix44.translate(-p.x, -p.y, -p.z) @ Matrix44.ucs(
            ux=ux, uy=uy, uz=uz, origin=p0
        )

    def _entity_anchor(self, entity: Any) -> Any:
        for name in ("insert", "location", "start", "center", "vtx0"):
            if entity.dxf.hasattr(name):
                with contextlib.suppress(Exception):
                    return Vec3(entity.dxf.get(name))
        with contextlib.suppress(Exception):
            extents = ezdxf_bbox.extents([entity], fast=True)
            if extents.has_data:
                return extents.center
        return Vec3(0.0, 0.0, 0.0)

    def _exact_points(self, entity: Any) -> None:
        entity_type = entity.dxftype()
        fields = {
            "LINE": ("start", "end"),
            "POINT": ("location",),
            "3DFACE": ("vtx0", "vtx1", "vtx2", "vtx3"),
            "SOLID": ("vtx0", "vtx1", "vtx2", "vtx3"),
            "TRACE": ("vtx0", "vtx1", "vtx2", "vtx3"),
        }[entity_type]
        if entity_type in {"SOLID", "TRACE"}:
            points = [
                self.transform_point(point)
                for point in entity.wcs_vertices(close=False)
            ]
            while points and len(points) < len(fields):
                points.append(points[-1])
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
        self.result.transformed[entity_type] += 1

    def _replace_by_polyline(
        self, entity: Any, vertices: Iterable[Any], closed: bool
    ) -> Any:
        layout = entity.get_layout()
        if layout is None:
            raise ConversionError("Entity is not assigned to a layout.")
        points = [self.transform_point(point) for point in vertices]
        if len(points) < (3 if closed else 2):
            raise ConversionError("A faceted entity produced too few vertices.")
        if closed and points[0].isclose(points[-1]):
            points.pop()
        attributes = _graphic_attributes(entity)
        same_z = (
            max(point.z for point in points) - min(point.z for point in points) <= 1e-10
        )
        if same_z and not self.target_crs.is_geocentric:
            attributes["elevation"] = float(points[0].z)
            replacement = layout.add_lwpolyline(
                [(point.x, point.y) for point in points],
                close=closed,
                dxfattribs=attributes,
            )
        else:
            replacement = layout.add_polyline3d(points, dxfattribs=attributes)
            replacement.close(closed)
        _copy_xdata(entity, replacement)
        layout.delete_entity(entity)
        return replacement

    def _polyline_or_curve(self, entity: Any) -> None:
        entity_type = entity.dxftype()
        if entity_type == "POLYLINE":
            mode = entity.get_mode()
            if mode in {"AcDb3dPolyline", "AcDbPolygonMesh", "AcDbPolyFaceMesh"}:
                points = [
                    self.transform_point(vertex.dxf.location)
                    for vertex in entity.vertices
                ]
                for vertex, point in zip(entity.vertices, points, strict=True):
                    vertex.dxf.location = point
                self.result.transformed[entity_type] += 1
                return
        path = make_path(entity)
        vertices = list(path.flattening(distance=self.job.curve_tolerance, segments=8))
        is_closed = bool(getattr(path, "is_closed", False))
        self._replace_by_polyline(entity, vertices, is_closed)
        self.result.approximated[entity_type] += 1

    def _hatch(self, entity: Any) -> None:
        # Keep the HATCH/MPOLYGON object and its fill definition.  Only boundary
        # paths are converted to dense polyline loops and reprojected.
        original_paths = list(entity.paths)
        paths = list(paths_from_hatch(entity))
        if len(paths) != len(original_paths):
            raise ConversionError("Hatch boundary path count is inconsistent.")
        loops: list[tuple[list[tuple[float, float, float]], int]] = []
        transformed_z: list[float] = []
        for path, boundary in zip(paths, original_paths, strict=True):
            points = [
                self.transform_point(point)
                for point in path.flattening(
                    distance=self.job.curve_tolerance, segments=8
                )
            ]
            if points and points[0].isclose(points[-1]):
                points.pop()
            if len(points) < 3:
                raise ConversionError(
                    "Hatch boundary produced fewer than three vertices."
                )
            transformed_z.extend(point.z for point in points)
            loops.append(
                ([(p.x, p.y, 0.0) for p in points], int(boundary.path_type_flags))
            )
        if not transformed_z:
            raise ConversionError("Hatch has no usable boundary vertices.")
        z_min = min(transformed_z)
        z_max = max(transformed_z)
        if z_max - z_min > max(1e-8, self.job.curve_tolerance * 1e-6):
            raise ConversionError(
                "The transformed hatch is not planar and cannot be represented by one CAD HATCH."
            )
        # Validate every boundary and its elevation before changing the source.
        entity.paths.clear()
        for points, flags in loops:
            entity.paths.add_polyline_path(points, is_closed=True, flags=flags)
        if entity.dxf.hasattr("elevation"):
            entity.dxf.elevation = Vec3(
                0.0, 0.0, sum(transformed_z) / len(transformed_z)
            )
        if entity.dxf.hasattr("extrusion"):
            entity.dxf.extrusion = Vec3(0.0, 0.0, 1.0)
        self.result.approximated[entity.dxftype()] += 1
        self.result.add_issue(
            "information",
            "hatch_pattern_local",
            "Faceted hatch boundaries were reprojected; the hatch pattern definition remains a CAD-local pattern.",
            entity,
        )

    def _leader(self, entity: Any) -> None:
        entity.set_vertices([self.transform_point(point) for point in entity.vertices])
        self.result.transformed[entity.dxftype()] += 1

    def _mesh(self, entity: Any) -> None:
        points = [self.transform_point(point) for point in entity.vertices]
        for index, point in enumerate(points):
            entity.vertices[index] = point
        self.result.transformed[entity.dxftype()] += 1

    def _viewport(self, entity: Any) -> None:
        # Paper-space viewport frames are layout geometry and must not be moved.
        # If paper-space transformation was explicitly requested, use a local
        # affine approximation to keep the rectangular viewport coherent.
        self._local_affine(entity, "viewport_local_affine")

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
            self.result.unresolved[entity_type] += 1
            self.result.add_issue(
                "error",
                "composite_unresolved",
                f"Original object retained without reprojection. {problem}",
                entity,
            )
            return []
        # Any failure after this point may have changed the layout. The caller
        # must abort this drawing rather than publish a partial explosion.
        exploded = list(entity.explode())
        self.result.exploded[entity_type] += 1
        return exploded

    def transform_entity(self, entity: Any) -> list[Any]:
        self.cancel.check()
        entity_type = entity.dxftype()
        handle = str(entity.dxf.get("handle", "") or "")
        layout_name = getattr(entity.get_layout(), "name", "<unknown>")
        try:
            if entity_type in self.COMPOSITE_TYPES:
                return self._explode_composite(entity)
            if entity_type in self.EXACT_POINT_TYPES:
                self._exact_points(entity)
            elif entity_type in self.CURVE_TYPES or entity_type == "POLYLINE":
                self._polyline_or_curve(entity)
            elif entity_type in {"HATCH", "MPOLYGON"}:
                self._hatch(entity)
            elif entity_type in {"LEADER"}:
                self._leader(entity)
            elif entity_type == "MESH":
                self._mesh(entity)
            elif entity_type == "VIEWPORT":
                self._viewport(entity)
            elif entity_type in self.NON_GEOMETRIC_TYPES:
                # These metadata records do not expose display geometry here.
                self.result.transformed[f"{entity_type}_PRESERVED"] += 1
            else:
                self._local_affine(entity)
        except (CancelledError, CoordinateTransformationError):
            raise
        except Exception as exc:
            self.result.unresolved[entity_type] += 1
            self.result.issues.append(
                EntityIssue(
                    severity="error",
                    code="entity_transformation_failed",
                    message=f"Drawing publication stopped after a failed entity transformation: {exc}",
                    layout=layout_name,
                    entity_type=entity_type,
                    handle=handle,
                )
            )
            raise ConversionError(
                f"Could not safely transform {entity_type} (handle {handle or 'unknown'}): {exc}. "
                "No output for this drawing was published because the object may have been partly changed."
            ) from exc
        return []

    def transform_layout(self, layout: Any) -> None:
        pending = list(layout)
        index = 0
        while index < len(pending):
            self.cancel.check()
            entity = pending[index]
            index += 1
            if not entity.is_alive:
                continue
            pending.extend(self.transform_entity(entity))

    def run(self) -> None:
        self.log(f"Coordinate operation: {self.operation_description}")
        if self.coordinate_operation.grids:
            for grid in self.coordinate_operation.grids:
                self.log(
                    f"Required local NTv2 grid: {grid['path']} ({grid['direction']})"
                )
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
        self.transform_layout(self.doc.modelspace())
        if self.job.transform_paper_space:
            for layout in self.doc.layouts:
                if layout.name != "Model":
                    self.transform_layout(layout)
        self.result.output_entity_count = len(self.doc.modelspace())

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

        # EPSG projected systems in the supplied list use metres.  Geographic
        # and geocentric CRSs cannot be represented by one ordinary CAD INSUNITS
        # value, so they are marked unitless and identified by the custom tags.
        self.doc.header["$INSUNITS"] = 6 if self.target_crs.is_projected else 0


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


def verify_dxf(path: Path) -> dict[str, Any]:
    """Reopen and audit a completed DXF before it is published."""
    try:
        document = ezdxf.readfile(str(path))
        auditor = document.audit()
    except Exception as exc:
        raise ConversionError(
            f"Output verification could not reopen the DXF: {exc}"
        ) from exc
    errors = len(getattr(auditor, "errors", []) or [])
    if errors:
        raise ConversionError(f"Output verification found {errors} DXF audit error(s).")
    return {
        "reopened": True,
        "audit_errors": errors,
        "audit_fixes": len(getattr(auditor, "fixes", []) or []),
        "modelspace_entities": len(document.modelspace()),
        "dxf_version": document.dxfversion,
    }


def convert_one_file(
    source: Path,
    job: ConversionJob,
    cancel: CancellationToken,
    log: LogCallback,
) -> tuple[FileResult, dict[str, Any]]:
    target = _safe_output_path(source, job)
    result = FileResult(input_path=str(source.resolve()))
    with prepared_dxf_input(source, job, cancel, log) as dxf_input:
        document, audit = load_dxf(dxf_input, job.audit_and_recover, log)
        engine = DrawingReprojector(document, job, result, cancel, log)
        engine.run()
        if result.unresolved and job.strict_unresolved:
            summary = ", ".join(
                f"{key}: {value}" for key, value in result.unresolved.items()
            )
            raise ConversionError(
                "Strict mode stopped the conversion because some objects could not be "
                f"reprojected. No output was published. Unresolved objects: {summary}"
            )
        with tempfile.TemporaryDirectory(prefix="cad_epsg_write_") as temp_dir:
            intermediate = Path(temp_dir) / f"{source.stem}.dxf"
            document.saveas(str(intermediate))
            verification = verify_dxf(intermediate)
            if verification["modelspace_entities"] != result.output_entity_count:
                raise ConversionError(
                    "Output verification found an unexpected model-space entity count: "
                    f"expected {result.output_entity_count}, reopened {verification['modelspace_entities']}."
                )
            cancel.check()
            if target.suffix.lower() == ".dxf":
                _atomic_copy(intermediate, target, job.overwrite)
            else:
                oda = detect_oda_converter(job.oda_executable)
                if not oda:
                    raise ConversionError(
                        "DWG output requires ODA File Converter. Choose DXF output or install ODA."
                    )
                log(
                    "Converting the reprojected temporary DXF to DWG with ODA File Converter."
                )
                converted = _oda_convert(
                    intermediate, "dwg", oda, job.dwg_timeout_seconds, cancel
                )
                try:
                    # A DWG is verified by an isolated ODA round trip back to DXF.
                    checked_dxf = _oda_convert(
                        converted, "dxf", oda, job.dwg_timeout_seconds, cancel
                    )
                    try:
                        verification = verify_dxf(checked_dxf)
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
                    _atomic_copy(converted, target, job.overwrite)
                finally:
                    shutil.rmtree(converted.parents[1], ignore_errors=True)
    result.output_path = str(target.resolve())
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
    }
    return result, metadata


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
    cancel = cancel or CancellationToken()
    progress = progress or (lambda _value, _message: None)
    log = log or (lambda _message: None)
    report_path = Path(job.output_directory) / f"report_{job.target_epsg}.json"
    total = len(job.input_paths)
    report: dict[str, Any] = {
        "application": APP_NAME,
        "version": APP_VERSION,
        "status": "running",
        "started_at_utc": _utc_now(),
        "finished_at_utc": None,
        "report_path": str(report_path.resolve()),
        "job": asdict(job),
        "operations": [],
        "files": [],
        "notes": [
            "Curves and bulged polylines are adaptively faceted before nonlinear CRS reprojection.",
            "Block references and dimensions are exploded to transform displayed world geometry.",
            "Proprietary objects that only expose an affine transform receive a local Jacobian transform and are listed in issues.",
            "Raster images, underlays and OLE payloads are not resampled or warped by this application.",
        ],
    }
    current_input: str | None = None
    try:
        for index, raw in enumerate(job.input_paths):
            source = Path(raw)
            current_input = str(source.resolve())
            cancel.check()
            progress(index / total, f"Reprojecting {source.name} ({index + 1}/{total})")
            log(f"\n--- {source.name} ---")
            result, operation = convert_one_file(source, job, cancel, log)
            report["files"].append(result.as_json())
            report["operations"].append(operation)
            current_input = None
            progress((index + 1) / total, f"Completed {source.name}")
        report["status"] = "completed"
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
        raise
    finally:
        report["finished_at_utc"] = _utc_now()
        report["completed_file_count"] = len(report["files"])
        try:
            _write_json_report(report, report_path)
        except (OSError, ValueError, TypeError) as exc:
            message = f"Could not write conversion report {report_path}: {exc}"
            if report["status"] == "completed":
                raise ConversionError(message) from exc
            # Preserve the original conversion failure if reporting also fails.
            log(message)
    return report


def inspect_transformation(
    source_epsg: int,
    target_epsg: int,
    allow_ballpark: bool,
    grid_directory: str | None = None,
) -> str:
    require_dependencies()
    source = CRS.from_epsg(source_epsg)
    target = CRS.from_epsg(target_epsg)
    operation = build_coordinate_operation(
        source_epsg, target_epsg, allow_ballpark, grid_directory
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
    if 2963 in (source_epsg, target_epsg):
        lines.append("EPSG:2963 axes: CAD X = Southing (P), CAD Y = Westing (M).")
    if not operation.best_available:
        lines.append(
            "A PROJ operation outside the local-grid stages has an unavailable better alternative."
        )
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
                pdsize=max(1, int(document.header.get("$PDSIZE", 1))),
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
        self.strict_var = tk.BooleanVar(value=True)
        self.ballpark_var = tk.BooleanVar(value=False)
        self.audit_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.oda_var = tk.StringVar()
        self.grid_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.progress_var = tk.DoubleVar(value=0.0)

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
            "maximum chord error before reprojection. Block references and dimensions are "
            "exploded so their displayed geometry is transformed in world coordinates.\n\n"
            "CAD objects that expose only an affine transform, including some proprietary or "
            "application-defined entities, are preserved and transformed with the local CRS "
            "Jacobian at their anchor. Every such case is listed in the JSON report. Strict "
            "mode prevents an output from being published if an entity cannot be transformed.\n\n"
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
            "Place pt73_e89.gsb, ptED_e89.gsb, ptLB_e89.gsb and ptLX_e89.gsb beside "
            "this script or executable, or select their folder in Advanced settings. "
            "Validate transformation shows the selected operation and required grids."
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
        self.progress.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
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
        if self.closing:
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
                self.tolerance_var.set("0.000001")
            elif source.is_projected and current == "0.000001":
                self.tolerance_var.set(str(DEFAULT_CURVE_TOLERANCE))

    def _validate_crs(self) -> None:
        try:
            text = inspect_transformation(
                parse_epsg(self.source_var.get()),
                parse_epsg(self.target_var.get()),
                self.ballpark_var.get(),
                self.grid_var.get().strip() or None,
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
                allow_ballpark=self.ballpark_var.get(),
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
        self._set_busy(True)
        self.progress_var.set(0)
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
                    self.progress_var.set(max(0, min(100, value * 100)))
                    self.status_var.set(message)
                elif kind == "done":
                    self.progress_var.set(100)
                    self.status_var.set("Conversion completed")
                    self._log("\nOutputs:")
                    for item in payload["files"]:
                        self._log(f"  {item['output_path']}")
                    self._log(f"Report: {payload['report_path']}")
                    self._set_busy(False)
                    self.cancel_token = None
                    if not self.closing:
                        messagebox.showinfo(
                            "Conversion complete",
                            f"Converted {len(payload['files'])} drawing(s).\n\nReport:\n{payload['report_path']}",
                            parent=self.root,
                        )
                elif kind == "cancelled":
                    self._log(payload)
                    self.status_var.set("Cancelled")
                    self._set_busy(False)
                    self.cancel_token = None
                elif kind == "error":
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
        row = 2
        checks = (
            ("Keep Z elevations in horizontal conversions", self.preserve_z_var),
            ("Transform paper-space geometry", self.paper_var),
            ("Stop if a geometric object cannot be transformed", self.strict_var),
            ("Allow ballpark datum transformations", self.ballpark_var),
            ("Audit and recover damaged DXF", self.audit_var),
            ("Overwrite existing output files", self.overwrite_var),
        )
        for text, variable in checks:
            ttk.Checkbutton(frame, text=text, variable=variable).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=3
            )
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
                for label in (oda_note, grid_note)
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
            "Source execution: Python 3.12 with Tcl/Tk, ezdxf, pyproj and Pillow "
            "(imported as PIL). Pip is the installer; Pillow is required by the preview. "
            "Pip also installs NumPy, FontTools, pyparsing, typing_extensions and certifi.\n\n"
            "See README.md or the opening documentation in script.py for environment "
            "activation, complete installation commands and the one-file build.\n\n"
            "The documented build embeds Python, the GUI runtime, packages and four "
            "NTv2 grids. DXF operation needs no separate Python or grid installation. "
            "Leave the grid folder blank to use embedded grids.\n\n"
            "For source execution, place pt73_e89.gsb, ptED_e89.gsb, ptLB_e89.gsb "
            "and ptLX_e89.gsb beside script.py, or select their folder in Advanced.\n\n"
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
    parser.add_argument("--curve-tolerance", type=float, default=None)
    parser.add_argument("--transform-paper-space", action="store_true")
    parser.add_argument("--allow-ballpark", action="store_true")
    parser.add_argument("--allow-unresolved", action="store_true")
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
        source_crs = CRS.from_epsg(source)
        curve_tolerance = arguments.curve_tolerance
        if curve_tolerance is None:
            curve_tolerance = (
                0.000001 if source_crs.is_geographic else DEFAULT_CURVE_TOLERANCE
            )
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
            strict_unresolved=not arguments.allow_unresolved,
            allow_ballpark=arguments.allow_ballpark,
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
