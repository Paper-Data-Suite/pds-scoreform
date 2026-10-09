"""Issue #225: privacy-bounded, read-only QR/PDS2 qualification.

No Core routing, answer scoring, publication, or student identity reporting.
The scan harness retains its input in a disposable temporary workspace only.
"""

from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

QrEngine = Literal["opencv", "zxing-cpp", "none"]
QrOutcome = Literal["valid_pds2", "invalid_pds2", "qr_unreadable", "page_load_error"]
REPORT_SCHEMA = "scoreform_issue225_qr_qualification_v1"


@dataclass(frozen=True, slots=True)
class PageQualification:
    """Deliberately excludes decoded text, locators, student data, and paths."""

    page: int
    outcome: QrOutcome
    engine: QrEngine
    image_width: int | None = None
    image_height: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.page, bool) or not isinstance(self.page, int) or self.page < 1:
            raise ValueError("page must be a positive integer")
        if self.outcome not in {"valid_pds2", "invalid_pds2", "qr_unreadable", "page_load_error"}:
            raise ValueError("unsupported qualification outcome")
        if self.engine not in {"opencv", "zxing-cpp", "none"}:
            raise ValueError("unsupported QR engine")
        if self.outcome == "page_load_error":
            if self.engine != "none" or self.image_width is not None or self.image_height is not None:
                raise ValueError("failed page loading cannot claim image or decoder")
        else:
            if (
                isinstance(self.image_width, bool)
                or not isinstance(self.image_width, int)
                or self.image_width < 1
                or isinstance(self.image_height, bool)
                or not isinstance(self.image_height, int)
                or self.image_height < 1
            ):
                raise ValueError("loaded pages require positive image dimensions")
            if self.outcome == "qr_unreadable" and self.engine != "none":
                raise ValueError("undecodable pages cannot claim a decoder")
            if self.outcome in {"valid_pds2", "invalid_pds2"} and self.engine == "none":
                raise ValueError("decoded payload requires a decoder")


def classify_detection(
    *,
    page: int,
    image: object,
    detection: object,
    parse_payload: Callable[[str], object],
) -> PageQualification:
    """Parse through Core's real validator, recording only non-sensitive status."""
    height, width = image.shape[:2]  # type: ignore[attr-defined]
    raw = getattr(detection, "raw_payload_text", None)
    if raw is None:
        return PageQualification(page, "qr_unreadable", "none", width, height)
    method = getattr(detection, "decode_method", None)
    engine: QrEngine = "zxing-cpp" if isinstance(method, str) and method.startswith("zxing-cpp:") else "opencv"
    try:
        parse_payload(raw)
    except Exception:
        return PageQualification(page, "invalid_pds2", engine, width, height)
    return PageQualification(page, "valid_pds2", engine, width, height)


def select_pages(total_pages: int, selection: tuple[int, ...] | None = None) -> tuple[int, ...]:
    """Require in-range, distinct, ascending page numbers; None selects all."""
    if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages < 1:
        raise ValueError("source must contain at least one page")
    if selection is None:
        return tuple(range(1, total_pages + 1))
    if not selection or any(
        isinstance(x, bool) or not isinstance(x, int) or not 1 <= x <= total_pages
        for x in selection
    ) or len(set(selection)) != len(selection):
        raise ValueError("selected pages must be unique and within the source")
    return tuple(sorted(selection))


def qualify_pages(
    *,
    total_pages: int,
    selection: tuple[int, ...] | None,
    load_page: Callable[[int], object],
    detect: Callable[[object, int], object],
    parse_payload: Callable[[str], object],
    on_page: Callable[[PageQualification], None] | None = None,
) -> tuple[PageQualification, ...]:
    """One page at a time; isolate conversion/detection failures by page."""
    result: list[PageQualification] = []
    for number in select_pages(total_pages, selection):
        try:
            image = load_page(number)
        except Exception:
            page = PageQualification(number, "page_load_error", "none")
        else:
            try:
                detected = detect(image, number)
                page = classify_detection(
                    page=number, image=image, detection=detected, parse_payload=parse_payload
                )
            except Exception:
                # Scanner exceptions are not authoritative decoded identities.
                height, width = image.shape[:2]  # type: ignore[attr-defined]
                page = PageQualification(number, "qr_unreadable", "none", width, height)
        result.append(page)
        if on_page is not None:
            on_page(page)
    return tuple(result)


def build_report(total_pages: int, pages: tuple[PageQualification, ...]) -> dict[str, object]:
    """Report contains only enumerated outcomes, engines, and image dimensions."""
    if not pages or any(page.page > total_pages for page in pages):
        raise ValueError("qualification results must be nonempty and in range")
    numbers = [page.page for page in pages]
    if len(set(numbers)) != len(numbers) or numbers != sorted(numbers):
        raise ValueError("page results must be unique and in source order")
    outcomes = Counter(page.outcome for page in pages)
    engines = Counter(page.engine for page in pages)
    return {
        "schema": REPORT_SCHEMA,
        "scope": "qr_decode_and_pds2_parse_only",
        "route_registration_checked": False,
        "student_identity_checked": False,
        "answer_scoring_performed": False,
        "raw_payloads_recorded": False,
        "source_total_pages": total_pages,
        "pages_examined": len(pages),
        "all_pages_examined": len(pages) == total_pages,
        "outcomes": {key: outcomes[key] for key in ("valid_pds2", "invalid_pds2", "qr_unreadable", "page_load_error")},
        "decoders": {key: engines[key] for key in ("opencv", "zxing-cpp", "none")},
        "pages": [asdict(page) for page in pages],
    }


def qualify_source_scan(
    source_path: str | Path,
    *,
    selected_pages: tuple[int, ...] | None = None,
    on_page: Callable[[PageQualification], None] | None = None,
) -> dict[str, object]:
    """Use actual ScoreForm retained page loading in a disposable Core workspace.

    The input is temporarily copied by Core; all intake and diagnostic files
    are deleted when the context exits normally. Never use the teacher's live
    OneDrive workspace or dispatch/score/publish in this qualification.
    """
    from tempfile import TemporaryDirectory

    from pds_core.pds2 import parse_pds2_payload
    from pds_core.scan_retention import retain_source_scan

    from scoreform.pds2_scan_dispatch import (
        detect_qr_payload_text,
        validate_pds2_scan_source,
    )
    from scoreform.retained_page import (
        load_retained_page_for_qr,
        retained_source_page_count,
    )

    source = validate_pds2_scan_source(source_path)
    with TemporaryDirectory(prefix="scoreform_issue225_qualification_") as temp:
        # Core retention canonicalizes its workspace root on Windows; use
        # that same root for every retained-page validation and decode.
        root = Path(temp).resolve(strict=True)
        retained = retain_source_scan(root, source)
        count = retained_source_page_count(retained, workspace_root=root)
        pages = qualify_pages(
            total_pages=count,
            selection=selected_pages,
            load_page=lambda number: load_retained_page_for_qr(
                retained, number, workspace_root=root
            ),
            detect=lambda image, number: _quiet_qualification_decode(
                detect_qr_payload_text,
                image,
                retained_source=retained,
                source_page_number=number,
                workspace_root=root,
            ),
            parse_payload=parse_pds2_payload,
            on_page=on_page,
        )
    return build_report(count, pages)


class _DiscardScanStdout:
    """Drop only nested scanner chatter; never accumulate sensitive paths."""

    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        return None


def _quiet_qualification_decode(detector: Callable[..., object], *args: object, **kwargs: object) -> object:
    """Prevent disposable diagnostic paths from reaching qualification stdout.

    This single-threaded local harness deliberately hides scanner-internal
    chatter, not its own sanitized per-page progress or report output.
    Production scan diagnostics are unchanged.
    """
    with redirect_stdout(_DiscardScanStdout()):
        return detector(*args, **kwargs)
