import datetime
import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
from pds_core.scan_retention import SourceRetentionError, retain_source_scan

from scoreform import workspace
from scoreform.config import (
    FULL_PAGE_DIAGNOSTICS_ENV,
    LOCAL_DEBUG_DIR,
    LOCAL_OUTPUTS_DIR,
    MAX_ASSIGNMENT_QUESTION_COUNT,
)
from scoreform.layouts import AnswerSheetLayout, get_layout
from scoreform.migration import migration_pending
from scoreform.paging import (
    page_count_for_question_count,
    question_count_for_page,
    question_range_for_page,
)
from scoreform.validation import (
    IDENTIFIER_PATTERN,
    is_safe_identifier,
    validate_identifier,
)

CORNER_ZONE_FRACTION = 0.22
MIN_REGISTRATION_SIZE_RATIO = 0.65
MAX_REGISTRATION_SIZE_RATIO = 4.0

QR_FAILURE_LABELS = {
    "input_file_missing": "Input file missing",
    "unsupported_input_type": "Unsupported input type",
    "source_retention_failed": "Source scan retention failure",
    "pdf2image_missing": "pdf2image missing",
    "poppler_missing": "Poppler unavailable",
    "pdf_conversion_failed": "PDF conversion/processing failure",
    "missing_qr": "Missing QR code",
    "malformed_qr": "Malformed QR payload",
    "unsafe_qr": "Unsafe QR payload",
    "assignment_lookup_failed": "Assignment lookup failure",
    "image_processing_failed": "Image loading/processing failure",
    "registration_or_scoring_failed": "Registration/scoring failure",
    "multi_page_assembly_failed": "Multi-page assessment assembly failure",
    "result_write_failed": "Result writing failure",
    "unknown_failed": "Unknown failure",
}

QR_BATCH_OUTCOME_LABELS = {
    "full_success": "FULL SUCCESS",
    "partial_success": "PARTIAL SUCCESS",
    "zero_success": "ZERO SUCCESS",
    "export_failure": "EXPORT FAILURE",
}

QR_PARTIAL_SUCCESS_WARNING = (
    "WARNING: Some pages failed or were skipped. "
    "Review failures before treating results as final."
)


@dataclass
class ManualScoringFailure:
    page_num: int | None
    reason: str


@dataclass
class ManualScoringSummary:
    pages_processed: int = 0
    pages_scored: int = 0
    failures: list[ManualScoringFailure] = field(default_factory=list)

    @property
    def pages_failed_skipped(self):
        return len(
            [failure for failure in self.failures if failure.page_num is not None]
        )

    def record_processed_page(self):
        self.pages_processed += 1

    def record_scored_page(self):
        self.pages_scored += 1

    def record_failure(self, page_num, reason):
        self.failures.append(ManualScoringFailure(page_num, reason))

    def format(self):
        lines = [
            "",
            "Manual scoring summary:",
            f"- Pages processed: {self.pages_processed}",
            f"- Pages scored: {self.pages_scored}",
            f"- Pages failed/skipped: {self.pages_failed_skipped}",
        ]

        if self.failures:
            lines.extend(["", "Failures:"])
            for failure in self.failures:
                if failure.page_num is None:
                    lines.append(f"- {failure.reason}")
                else:
                    lines.append(f"- Page {failure.page_num}: {failure.reason}")

        if self.pages_scored == 0:
            lines.extend(["", "No pages were scored."])

        if self.pages_failed_skipped:
            lines.extend(
                [
                    "",
                    "WARNING: Some pages were not scored; results may be incomplete.",
                    "Review failed pages before treating results as final.",
                ]
            )
        elif self.failures:
            lines.extend(
                [
                    "",
                    "WARNING: Manual scoring did not complete successfully.",
                    "Review the failure details before retrying.",
                ]
            )

        return "\n".join(lines)


class ManualScoringResults(list):
    def __init__(self, *args, summary=None):
        super().__init__(*args)
        self.summary = summary or ManualScoringSummary()


@dataclass
class QRBatchFailure:
    page_num: int | None
    category: str
    reason: str
    class_id: str | None = None
    assignment_id: str | None = None
    student_id: str | None = None


@dataclass
class QRBatchSummary:
    pages_processed: int = 0
    pages_scored: int = 0
    failures: list[QRBatchFailure] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    diagnostic_paths: list[str] = field(default_factory=list)
    results_written: bool = False
    result_write_failed: bool = False

    @property
    def pages_skipped_failed(self):
        return len([failure for failure in self.failures if failure.page_num is not None])

    @property
    def file_failures(self):
        return [failure for failure in self.failures if failure.page_num is None]

    def record_processed_page(self):
        self.pages_processed += 1

    def record_scored_page(self):
        self.pages_scored += 1

    def record_failure(self, page_num, category, reason):
        self.failures.append(QRBatchFailure(page_num, category, reason))

    def record_file_failure(self, category, reason):
        self.record_failure(None, category, reason)

    def record_results_written(self, output_paths):
        self.results_written = True
        self.output_paths = list(dict.fromkeys(output_paths))

    def record_diagnostics(self, diagnostic_paths):
        self.diagnostic_paths = list(
            dict.fromkeys([*self.diagnostic_paths, *diagnostic_paths])
        )

    def record_result_write_failed(self, output_paths=None):
        self.result_write_failed = True
        if output_paths:
            self.output_paths = list(dict.fromkeys(output_paths))
        self.failures.append(
            QRBatchFailure(None, "result_write_failed", "results could not be written")
        )

    def failure_counts(self):
        counts = {}
        for failure in self.failures:
            counts[failure.category] = counts.get(failure.category, 0) + 1
        return counts

    def outcome(self):
        if self.result_write_failed:
            return "export_failure"
        if self.pages_scored == 0:
            return "zero_success"
        if not self.results_written:
            return "export_failure"
        if self.failures:
            return "partial_success"
        return "full_success"

    def exit_code(self):
        if self.outcome() in {"full_success", "partial_success"}:
            return 0
        return 1

    def format(self):
        outcome = self.outcome()
        lines = [
            "",
            "QR-Aware Batch Summary",
            "",
            f"Batch status: {QR_BATCH_OUTCOME_LABELS[outcome]}",
        ]

        if outcome == "partial_success":
            lines.extend(["", QR_PARTIAL_SUCCESS_WARNING])
        elif outcome == "zero_success":
            lines.extend(["", "Error: No pages were scored successfully."])
        elif outcome == "export_failure":
            lines.extend(["", "Error: Failed to export results."])

        lines.extend(
            [
                "",
                f"Pages processed: {self.pages_processed}",
                f"Pages scored: {self.pages_scored}",
                f"Pages skipped/failed: {self.pages_skipped_failed}",
                f"File/batch failures: {len(self.file_failures)}",
            ]
        )

        counts = self.failure_counts()
        if counts:
            lines.extend(["", "Failures:"])
            for category, label in QR_FAILURE_LABELS.items():
                count = counts.get(category, 0)
                if count:
                    lines.append(f"- {label}: {count}")

        page_failures = [failure for failure in self.failures if failure.page_num is not None]
        if page_failures:
            lines.extend(["", "Skipped pages:"])
            for failure in page_failures:
                lines.append(f"- Page {failure.page_num}: {failure.reason}")

        if self.file_failures:
            lines.extend(["", "File/batch failure details:"])
            for failure in self.file_failures:
                lines.append(f"- {failure.reason}")

        if self.diagnostic_paths:
            lines.extend(["", "QR failure diagnostics:"])
            lines.extend(self.diagnostic_paths)

        lines.extend(["", "Results written:"])
        if self.results_written:
            if self.output_paths:
                lines.extend(self.output_paths)
            else:
                lines.append("Yes")
        elif self.result_write_failed:
            lines.append("No - result writing failed.")
            if self.output_paths:
                lines.append("Attempted output path(s):")
                lines.extend(self.output_paths)
        else:
            lines.append("No results were written.")

        if (self.failures or self.result_write_failed) and outcome != "partial_success":
            lines.extend(["", "Review failures before treating results as final."])

        return "\n".join(lines)

    def print(self):
        print(self.format())


class QRBatchResults(list):
    def __init__(self, *args, summary=None, retained_source=None):
        super().__init__(*args)
        self.summary = summary or QRBatchSummary()
        self.retained_source = retained_source


@dataclass
class QRDecodeResult:
    metadata: dict | None
    failure_category: str | None = None
    failure_reason: str | None = None
    diagnostic_paths: list[str] = field(default_factory=list)


def order_points(pts):
    """Orders points in top-left, top-right, bottom-left, bottom-right order."""
    rect = np.zeros((4, 2), dtype="float32")

    # Top-left point has the smallest sum; bottom-right has the largest sum.
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[3] = pts[np.argmax(s)]

    # Top-right point has the smallest difference; bottom-left has the largest difference.
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[2] = pts[np.argmax(diff)]

    return rect


def _infer_question_count(answer_key, default=10):
    """Infer the question count from a validated answer_key dict if possible."""
    if not isinstance(answer_key, dict) or not answer_key:
        return default

    keys = []
    for key in answer_key.keys():
        if isinstance(key, int):
            keys.append(key)
        elif isinstance(key, str) and key.isdigit():
            keys.append(int(key))
        else:
            return default

    if not keys:
        return default

    max_question = max(keys)
    if max_question > MAX_ASSIGNMENT_QUESTION_COUNT:
        return default

    if set(keys) == set(range(1, max_question + 1)):
        return max_question
    return default


def non_overwriting_path(path):
    """Return path unchanged unless it exists, then append a numeric suffix."""
    path = os.fspath(path)
    if not os.path.exists(path):
        return path

    root, ext = os.path.splitext(path)
    counter = 2
    while True:
        candidate = f"{root}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def _expected_corner_regions(img_w, img_h):
    """Return expected registration zones as (expected_center, bounds) pairs."""
    zone_w = img_w * CORNER_ZONE_FRACTION
    zone_h = img_h * CORNER_ZONE_FRACTION

    return [
        ((img_w * 0.1, img_h * 0.1), (0, 0, zone_w, zone_h)),
        ((img_w * 0.9, img_h * 0.1), (img_w - zone_w, 0, img_w, zone_h)),
        ((img_w * 0.1, img_h * 0.9), (0, img_h - zone_h, zone_w, img_h)),
        ((img_w * 0.9, img_h * 0.9), (img_w - zone_w, img_h - zone_h, img_w, img_h)),
    ]


def _registration_size_bounds(img_w, img_h, layout=None):
    resolved = get_layout() if layout is None else layout
    scale = min(img_w / resolved.img_width, img_h / resolved.img_height)
    expected_size = resolved.registration_size * scale
    min_size = max(12, expected_size * MIN_REGISTRATION_SIZE_RATIO)
    max_size = expected_size * MAX_REGISTRATION_SIZE_RATIO
    return min_size, max_size, expected_size


def _score_registration_candidate(candidate, expected_center, expected_size):
    cX, cY = candidate["center"]
    ex_x, ex_y = expected_center
    distance = np.sqrt((cX - ex_x) ** 2 + (cY - ex_y) ** 2)
    distance_score = distance / max(expected_size, 1)

    aspect_ratio = candidate["width"] / float(candidate["height"])
    aspect_score = abs(np.log(aspect_ratio))

    size_score = abs(candidate["area"] - (expected_size * expected_size))
    size_score = size_score / max(expected_size * expected_size, 1)

    fill_score = max(0, 0.6 - candidate["fill_density"])

    return distance_score + aspect_score + (0.25 * size_score) + fill_score


def _dark_component_candidates(
    thresh,
    bounds,
    expected_center,
    min_size,
    max_size,
    expected_size,
):
    x_min, y_min, x_max, y_max = [int(round(v)) for v in bounds]
    roi = thresh[y_min:y_max, x_min:x_max]
    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(
        roi,
        connectivity=8,
    )

    min_area = max(80, min_size * min_size * 0.35)
    candidates = []

    for label in range(1, num_labels):
        x, y, w, h, area = stats[label]
        if area < min_area:
            continue
        if w < min_size or h < min_size:
            continue
        if w > max_size or h > max_size:
            continue

        aspect_ratio = w / float(h)
        if not 0.35 <= aspect_ratio <= 3.0:
            continue

        bounding_area = w * h
        if bounding_area == 0:
            continue

        fill_density = area / float(bounding_area)
        if fill_density < 0.35:
            continue

        cX = int(round(x_min + centroids[label][0]))
        cY = int(round(y_min + centroids[label][1]))
        candidate = {
            "center": (cX, cY),
            "width": w,
            "height": h,
            "area": area,
            "fill_density": fill_density,
        }
        candidate["score"] = _score_registration_candidate(
            candidate,
            expected_center,
            expected_size,
        )
        candidates.append(candidate)

    return candidates


def _find_registration_mark_centers(thresh, img_w, img_h, layout=None):
    """Find registration mark centers using per-corner dark-component searches."""
    min_size, max_size, expected_size = _registration_size_bounds(img_w, img_h, layout)
    candidates = []
    corner_centers = []

    for expected_center, bounds in _expected_corner_regions(img_w, img_h):
        zone_candidates = _dark_component_candidates(
            thresh,
            bounds,
            expected_center,
            min_size,
            max_size,
            expected_size,
        )
        candidates.extend(candidate["center"] for candidate in zone_candidates)

        if zone_candidates:
            best_candidate = min(
                zone_candidates,
                key=lambda candidate: candidate["score"],
            )
            corner_centers.append(best_candidate["center"])

    return candidates, corner_centers


def _classify_answer_row(row_filled, layout=None):
    """Classify one question from (fill_ratio, letter) pairs."""
    resolved = get_layout() if layout is None else layout
    ranked = sorted(row_filled, reverse=True, key=lambda item: item[0])
    best_fill, best_letter = ranked[0]

    if best_fill < resolved.strong_mark_fill_ratio:
        return "BLANK"

    secondary_threshold = max(
        resolved.possible_secondary_fill_ratio,
        best_fill * resolved.possible_secondary_relative_ratio,
    )
    if any(fill >= secondary_threshold for fill, _ in ranked[1:]):
        return "AMBIGUOUS"

    return best_letter


def score_image(
    img,
    answer_key,
    page_num=1,
    debug_dir=None,
    question_count=None,
    question_start=1,
    layout: AnswerSheetLayout | None = None,
):
    """Scores a single pre-loaded OpenCV image and returns structured data."""
    if debug_dir is None:
        debug_dir = os.fspath(
            workspace.get_scoreform_workspace_root() / LOCAL_DEBUG_DIR
        )

    layout = get_layout() if layout is None else layout
    debug_img = img.copy()
    if question_count is None:
        question_count = _infer_question_count(answer_key, default=10)

    if not isinstance(question_count, int) or question_count < 1:
        question_count = 10
    if (
        not isinstance(question_start, int)
        or isinstance(question_start, bool)
        or question_start < 1
    ):
        question_start = 1

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]

    img_h, img_w = img.shape[:2]
    candidates, corner_centers = _find_registration_mark_centers(
        thresh, img_w, img_h, layout
    )

    # Draw debug information on debug_img
    for cX, cY in candidates:
        cv2.circle(debug_img, (cX, cY), 20, (255, 0, 0), 2)  # All candidates in blue

    for cX, cY in corner_centers:
        cv2.circle(debug_img, (cX, cY), 20, (0, 255, 0), 4)  # Selected corners in green

    debug_corners_filename = f"debug_corners_page_{page_num}.png"
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        debug_corners_filename = os.path.join(debug_dir, debug_corners_filename)
    debug_corners_filename = non_overwriting_path(debug_corners_filename)
    cv2.imwrite(debug_corners_filename, debug_img)
    print(f"Saved {debug_corners_filename}")

    if len(corner_centers) != 4:
        print(
            f"Error: Could not confidently detect 4 registration marks on page {page_num}.\n"
            f"Found {len(corner_centers)} marks out of {len(candidates)} candidates."
        )
        return None

    print(f"Page {page_num} Selected Corner Centers: {corner_centers}")

    corner_centers = np.array(corner_centers, dtype="float32")
    rect = order_points(corner_centers)

    # Compute perspective transform
    M = cv2.getPerspectiveTransform(rect, layout.dst_points)
    warped = cv2.warpPerspective(img, M, (layout.img_width, layout.img_height))

    warped_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    warped_thresh = cv2.threshold(
        warped_gray,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]

    score = 0
    results = []

    # Check each question
    for i, slot in enumerate(layout.question_slots[:question_count]):
        row_filled = []

        for box in slot.boxes:
            # Extract ROI for the box.
            # Inset avoids counting the black border of the box itself.
            inset = layout.mark_inset
            roi = warped_thresh[
                box.y + inset : box.y + box.size - inset,
                box.x + inset : box.x + box.size - inset,
            ]

            # Count white pixels (filled area)
            filled_pixels = cv2.countNonZero(roi)
            total_pixels = roi.shape[0] * roi.shape[1]
            fill_ratio = filled_pixels / total_pixels
            row_filled.append((fill_ratio, box.choice))

        answer = _classify_answer_row(row_filled, layout)

        # Score it
        correct = False
        question_number = question_start + i
        if answer == answer_key.get(question_number, ""):
            score += 1
            correct = True

        results.append(
            {
                "Q": question_number,
                "Answer": answer,
                "Correct": correct,
            }
        )

    print(f"\n--- Page {page_num} Final Score: {score}/{question_count} ---")
    for r in results:
        print(f"Q{r['Q']}: {r['Answer']} ({'Correct' if r['Correct'] else 'Wrong'})")

    # Save a debug image
    debug_filename = f"debug_warped_page_{page_num}.png"
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        debug_filename = os.path.join(debug_dir, debug_filename)
    debug_filename = non_overwriting_path(debug_filename)
    cv2.imwrite(debug_filename, warped)
    print(f"Saved {debug_filename} for visual verification.\n")

    return {
        "page_num": page_num,
        "score": score,
        "total_points": question_count,
        "answers": results,
    }


def process_file(file_path, answer_key):
    """Processes a file, checking if it is a PDF or an image, and scores it.
    Returns list-compatible results with manual scoring failure accounting."""

    all_results = ManualScoringResults()
    summary = all_results.summary
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist.")
        summary.record_failure(None, f"Input file does not exist: {file_path}")
        return all_results

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError
        except ImportError:
            print("Error: The 'pdf2image' module is not installed.")
            print("Please run: pip install pdf2image")
            summary.record_failure(None, "PDF processing support is not installed.")
            return all_results

        print("PDF detected. Converting pages to images...")

        try:
            pages = convert_from_path(file_path)

            for page_num, page in enumerate(pages, start=1):
                summary.record_processed_page()
                print(f"Scoring Page {page_num}...")

                try:
                    # Convert PIL image to OpenCV format (RGB to BGR)
                    open_cv_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
                    res = score_image(
                        open_cv_image,
                        answer_key,
                        page_num,
                        question_count=_infer_question_count(answer_key, default=10),
                    )
                    if res:
                        # Attach source file information to each page result
                        res["source_file"] = file_path
                        all_results.append(res)
                        summary.record_scored_page()
                    else:
                        reason = "registration/corner detection failed."
                        print(f"Page {page_num}: {reason}")
                        summary.record_failure(page_num, reason)
                except Exception as e:
                    reason = f"page processing failed: {e}"
                    print(f"Page {page_num}: {reason}")
                    summary.record_failure(page_num, reason)

        except PDFInfoNotInstalledError:
            print("Error: Poppler is not installed or not in PATH.")
            print(
                "Please install Poppler and add its 'bin' folder to your system PATH."
            )
            print("Then test with: pdftoppm -h")
            summary.record_failure(None, "PDF conversion failed because Poppler is unavailable.")

        except Exception as e:
            print(f"Error while processing PDF: {e}")
            summary.record_failure(None, f"PDF conversion/processing failed: {e}")

    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        summary.record_processed_page()
        try:
            img = cv2.imread(file_path)
        except Exception as e:
            reason = f"image could not be read or loaded: {e}"
            print(f"Page 1: {reason}")
            summary.record_failure(1, reason)
            return all_results

        if img is None:
            print(f"Error: Could not read image {file_path}")
            summary.record_failure(1, "image could not be read or loaded.")
            return all_results

        print("Scoring Image...")
        try:
            res = score_image(
                img,
                answer_key,
                page_num=1,
                question_count=_infer_question_count(answer_key, default=10),
            )
            if res:
                res["source_file"] = file_path
                all_results.append(res)
                summary.record_scored_page()
            else:
                reason = "registration/corner detection failed."
                print(f"Page 1: {reason}")
                summary.record_failure(1, reason)
        except Exception as e:
            reason = f"page processing failed: {e}"
            print(f"Page 1: {reason}")
            summary.record_failure(1, reason)

    else:
        print(
            f"Error: Unsupported file extension '{ext}'. "
            "Please provide a PDF or an image."
        )
        summary.record_failure(None, f"Unsupported input type: {ext or '(none)'}")

    return all_results


QR_IDENTIFIER_PATTERN = IDENTIFIER_PATTERN


def is_safe_qr_identifier(value):
    """Return True when a QR field contains only safe identifier characters."""
    return is_safe_identifier(value)


def validate_qr_identifier(field_name, value):
    """Validate a single QR identifier field and print an error when unsafe."""
    return validate_identifier(field_name, value, context="QR")


def validate_qr_metadata(qr_metadata):
    """Validate QR metadata fields before they are used as path material."""
    if not isinstance(qr_metadata, dict):
        print("Error: QR metadata is not a dictionary.")
        return False

    for field_name in ["class_id", "assignment_id", "student_id"]:
        if field_name not in qr_metadata:
            print(f"Error: QR metadata missing required field '{field_name}'.")
            return False
        if not validate_qr_identifier(field_name, qr_metadata[field_name]):
            return False

    page = qr_metadata.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        print("Error: QR metadata missing a valid positive integer 'page'.")
        return False
    return True


def parse_qr_payload(payload):
    """Reject scan payload parsing until PDS2 dispatch is implemented."""
    migration_pending("QR payload parsing", "#143")


def _try_decode_qr(detector, img):
    """Return decoded QR payload text, or None when no QR is detected."""
    data, _, _ = detector.detectAndDecode(img)
    if data:
        return data
    return None


def _as_grayscale(img):
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _qr_preprocess_attempts(img):
    """Yield a bounded set of QR decode images from least to most processed."""
    yield "raw", img

    gray = _as_grayscale(img)
    if len(img.shape) != 2:
        yield "grayscale", gray

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    yield "otsu threshold", cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY | cv2.THRESH_OTSU,
    )[1]
    yield "otsu inverted threshold", cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]
    yield "adaptive threshold", cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        5,
    )
    yield "binary threshold", cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)[1]

    for scale in (1.5, 2.0, 3.0):
        yield (
            f"{scale:g}x upscale",
            cv2.resize(
                img,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            ),
        )
        yield (
            f"grayscale {scale:g}x upscale",
            cv2.resize(
                gray,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            ),
        )


def _expected_qr_crop_candidates(img):
    """Yield named upper-right crops around the ScoreForm template QR location."""
    h, w = img.shape[:2]
    crop_bounds = [
        ("broad_1", 0.58, 0.00, 1.00, 0.38),
        ("broad_2", 0.50, 0.00, 1.00, 0.48),
        ("broad_3", 0.65, 0.04, 0.98, 0.30),
        ("tight", 0.68, 0.06, 0.92, 0.28),
    ]

    for label, x1f, y1f, x2f, y2f in crop_bounds:
        x1 = max(0, int(w * x1f))
        y1 = max(0, int(h * y1f))
        x2 = min(w, int(w * x2f))
        y2 = min(h, int(h * y2f))
        if x2 > x1 and y2 > y1:
            yield label, img[y1:y2, x1:x2]


def _expected_qr_crops(img):
    """Yield upper-right crop images for backward-compatible callers."""
    for _, crop in _expected_qr_crop_candidates(img):
        yield crop


def _pad_qr_crop(crop, border_fraction=0.15):
    """Add a white quiet-zone border around a QR crop."""
    border = max(4, int(round(max(crop.shape[:2]) * border_fraction)))
    fill = 255 if len(crop.shape) == 2 else (255, 255, 255)
    return cv2.copyMakeBorder(
        crop,
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=fill,
    )


def _rotate_qr_crop(crop, angle):
    """Rotate a QR crop around its center using a white background."""
    h, w = crop.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    fill = 255 if len(crop.shape) == 2 else (255, 255, 255)
    return cv2.warpAffine(
        crop,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=fill,
    )


def _tight_qr_crop_attempts(crop):
    """Yield bounded enhanced attempts for the known ScoreForm QR region."""
    gray = _as_grayscale(crop)
    normalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    threshold = cv2.threshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        0,
        255,
        cv2.THRESH_BINARY | cv2.THRESH_OTSU,
    )[1]
    kernel = np.ones((2, 2), dtype=np.uint8)
    opened = cv2.morphologyEx(threshold, cv2.MORPH_OPEN, kernel)
    closed = cv2.morphologyEx(threshold, cv2.MORPH_CLOSE, kernel)

    prepared = [
        ("grayscale normalized", normalized),
        ("otsu threshold", threshold),
        ("otsu opened", opened),
        ("otsu closed", closed),
    ]
    for label, candidate in prepared:
        yield label, candidate
        for scale in (4.0, 5.0):
            yield (
                f"{label} {scale:g}x upscale",
                cv2.resize(
                    candidate,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_CUBIC,
                ),
            )

    for label, candidate in [("raw", crop), *prepared]:
        padded = _pad_qr_crop(candidate)
        yield f"{label} padded", padded
        for scale in (2.0, 3.0, 4.0, 5.0):
            yield (
                f"{label} padded {scale:g}x upscale",
                cv2.resize(
                    padded,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_CUBIC,
                ),
            )

    padded_normalized = _pad_qr_crop(normalized)
    for angle in (-3, -2, -1, 1, 2, 3):
        rotated = _rotate_qr_crop(padded_normalized, angle)
        yield (
            f"grayscale normalized padded rotated {angle:+g} degrees 3x upscale",
            cv2.resize(
                rotated,
                None,
                fx=3.0,
                fy=3.0,
                interpolation=cv2.INTER_CUBIC,
            ),
        )


def _qr_candidate_images(img):
    for label, candidate in _qr_preprocess_attempts(img):
        yield label, candidate

    for crop_index, (crop_label, crop) in enumerate(
        _expected_qr_crop_candidates(img),
        start=1,
    ):
        for label, candidate in _qr_preprocess_attempts(crop):
            yield f"crop {crop_index} ({crop_label}) {label}", candidate
        if crop_label == "tight":
            for label, candidate in _tight_qr_crop_attempts(crop):
                yield f"crop {crop_index} ({crop_label}) {label}", candidate


def _sanitize_output_stem(file_path):
    stem = os.path.splitext(os.path.basename(os.fspath(file_path or "scan")))[0]
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return sanitized or "scan"


def _dated_local_output_dir(category, now=None, workspace_root=None):
    timestamp = now or datetime.datetime.now()
    if workspace_root is None:
        workspace_root = workspace.get_scoreform_workspace_root()
    output_dir = os.fspath(
        workspace_root.joinpath(
            LOCAL_OUTPUTS_DIR,
            category,
            timestamp.strftime("%Y-%m-%d"),
        )
    )
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _write_diagnostic_image(path, image):
    output_path = non_overwriting_path(path)
    if cv2.imwrite(output_path, image):
        return output_path
    print(f"Warning: Could not save QR failure diagnostic image: {output_path}")
    return None


def _full_page_diagnostics_enabled():
    value = os.environ.get(FULL_PAGE_DIAGNOSTICS_ENV, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def save_qr_failure_diagnostics(
    img,
    file_path,
    page_num,
    now=None,
    workspace_root=None,
):
    """Save privacy-minimized QR failure images and return their paths."""
    if img is None:
        return []

    try:
        output_dir = _dated_local_output_dir(
            "qr_failures",
            now=now,
            workspace_root=workspace_root,
        )
    except OSError as error:
        print(f"Warning: Could not create QR failure diagnostic folder: {error}")
        return []
    stem = f"{_sanitize_output_stem(file_path)}_page_{page_num}"
    images = []
    crops = dict(_expected_qr_crop_candidates(img))

    for crop_label in ("broad_1", "broad_3", "tight"):
        crop = crops.get(crop_label)
        if crop is not None:
            suffix = "qr_region" if crop_label == "broad_1" else f"qr_region_{crop_label}"
            images.append((f"{stem}_{suffix}.png", crop))

    tight_crop = crops.get("tight")
    if tight_crop is not None:
        gray = _as_grayscale(tight_crop)
        threshold = cv2.threshold(
            cv2.GaussianBlur(gray, (3, 3), 0),
            0,
            255,
            cv2.THRESH_BINARY | cv2.THRESH_OTSU,
        )[1]
        padded = _pad_qr_crop(threshold)
        padded_5x = cv2.resize(
            padded,
            None,
            fx=5.0,
            fy=5.0,
            interpolation=cv2.INTER_CUBIC,
        )
        images.extend(
            [
                (f"{stem}_qr_crop_tight_threshold.png", threshold),
                (f"{stem}_qr_crop_tight_threshold_padded_5x.png", padded_5x),
            ]
        )

    if _full_page_diagnostics_enabled():
        images.append((f"{stem}_full_page_debug.png", img))

    saved_paths = []
    for filename, image in images:
        saved_path = _write_diagnostic_image(
            os.path.join(output_dir, filename),
            image,
        )
        if saved_path:
            saved_paths.append(saved_path)

    if saved_paths:
        print(f"Saved QR failure diagnostics to {output_dir}")
    return saved_paths


def _decode_qr_from_image_with_status(
    img,
    file_path=None,
    page_num=1,
    workspace_root=None,
):
    """Decode QR metadata and return structured failure status when it fails."""
    if img is None:
        print("Error: Provided image is None")
        return QRDecodeResult(
            None,
            "image_processing_failed",
            "image could not be loaded or processed",
        )

    detector = cv2.QRCodeDetector()

    data = None
    success_label = None

    for label, candidate in _qr_candidate_images(img):
        try:
            data = _try_decode_qr(detector, candidate)
        except Exception as e:
            print(f"Error: Exception while decoding QR: {e}")
            return QRDecodeResult(
                None,
                "image_processing_failed",
                "QR decoding failed while processing the image",
            )
        if data:
            success_label = label
            break

    if not data:
        print("No QR code detected after raw/preprocessed decode attempts.")
        diagnostic_paths = save_qr_failure_diagnostics(
            img,
            file_path,
            page_num,
            workspace_root=workspace_root,
        )
        return QRDecodeResult(
            None,
            "missing_qr",
            "missing QR code",
            diagnostic_paths,
        )

    parsed = parse_qr_payload(data)
    if parsed is None:
        print(f"QR code detected but payload invalid: '{data}'")
        return QRDecodeResult(None, "malformed_qr", "invalid QR payload")

    if not validate_qr_metadata(parsed):
        print(f"QR code payload failed validation: '{data}'")
        return QRDecodeResult(None, "unsafe_qr", "unsafe QR payload")

    if success_label != "raw":
        print(f"QR decoded using {success_label} fallback.")

    return QRDecodeResult(parsed)


def decode_qr_from_image(img):
    """Decode a QR code from an OpenCV image and parse its ScoreForm payload.

    Returns parsed metadata dict or None on failure.
    """
    return _decode_qr_from_image_with_status(img).metadata


def _default_qr_failure_reason(category):
    return {
        "missing_qr": "missing QR code",
        "malformed_qr": "invalid QR payload",
        "unsafe_qr": "unsafe QR payload",
        "assignment_lookup_failed": "assignment lookup failed",
        "image_processing_failed": "image loading/processing failed",
        "registration_or_scoring_failed": "registration/scoring failed",
    }.get(category, "failed")


def _record_qr_failure(
    summary,
    page_num,
    category,
    reason=None,
    *,
    class_id=None,
    assignment_id=None,
    student_id=None,
):
    if summary is not None:
        summary.failures.append(
            QRBatchFailure(
                page_num,
                category,
                reason or _default_qr_failure_reason(category),
                class_id,
                assignment_id,
                student_id,
            )
        )


def _record_qr_file_failure(summary, category, reason):
    if summary is not None:
        summary.record_file_failure(category, reason)


def _record_qr_success(summary):
    if summary is not None:
        summary.record_scored_page()


def _record_qr_processed(summary):
    if summary is not None:
        summary.record_processed_page()


def _record_qr_results_written(summary, output_paths):
    if summary is not None:
        summary.record_results_written(output_paths)


def _record_qr_result_write_failed(summary, output_paths=None):
    if summary is not None:
        summary.record_result_write_failed(output_paths)


def _qr_output_paths_for_results(
    all_results,
    explicit_output_file=None,
    workspace_root=None,
):
    migration_pending("QR-aware result routing", "#139 and #143")


def print_qr_batch_summary(summary):
    if summary is not None:
        summary.print()


def save_qr_batch_summary(summary, source_file, now=None, workspace_root=None):
    """Save the QR-aware terminal summary to a dated local text file."""
    if summary is None:
        return None

    timestamp = now or datetime.datetime.now()
    try:
        output_dir = _dated_local_output_dir(
            "qr_batch_summaries",
            now=timestamp,
            workspace_root=workspace_root,
        )
        filename = (
            f"{_sanitize_output_stem(source_file)}_"
            f"{timestamp.strftime('%Y-%m-%d_%H%M')}_summary.txt"
        )
        output_path = non_overwriting_path(os.path.join(output_dir, filename))
        with open(output_path, "w", encoding="utf-8") as summary_file:
            summary_file.write(summary.format().lstrip())
            summary_file.write("\n")
    except OSError as error:
        print(f"Warning: Could not save QR batch summary: {error}")
        return None

    print(f"Saved QR batch summary to {output_path}")
    return output_path


def update_qr_batch_result_write_status(
    all_results,
    export_success,
    explicit_output_file=None,
    workspace_root=None,
):
    summary = getattr(all_results, "summary", None)
    output_paths = _qr_output_paths_for_results(
        all_results,
        explicit_output_file,
        workspace_root=workspace_root,
    )
    if export_success:
        _record_qr_results_written(summary, output_paths)
    else:
        _record_qr_result_write_failed(summary, output_paths)


def get_qr_batch_summary(all_results):
    return getattr(all_results, "summary", None)


def _score_page_qr_aware_with_summary(
    img,
    page_num=1,
    file_path=None,
    summary=None,
    workspace_root=None,
):
    result = _score_page_qr_aware(
        img,
        page_num,
        file_path,
        summary=summary,
        workspace_root=workspace_root,
    )
    if result is not None:
        _record_qr_success(summary)
    return result


def _score_page_qr_aware_decode_metadata(
    img,
    page_num,
    summary,
    file_path=None,
    workspace_root=None,
):
    decoded = _decode_qr_from_image_with_status(
        img,
        file_path=file_path,
        page_num=page_num,
        workspace_root=workspace_root,
    )
    if decoded.metadata is None:
        _record_qr_failure(
            summary,
            page_num,
            decoded.failure_category or "unknown_failed",
            decoded.failure_reason,
        )
        if summary is not None and decoded.diagnostic_paths:
            summary.record_diagnostics(decoded.diagnostic_paths)
    return decoded.metadata


def _score_page_qr_aware_assignment_path(
    class_id,
    assignment_id,
    workspace_root=None,
):
    migration_pending("QR-aware assignment lookup", "#139 and #143")


def _load_qr_aware_assignment(assignment_path, page_num, summary):
    if not os.path.exists(assignment_path):
        print(f"Error: Assignment file not found: {assignment_path}")
        _record_qr_failure(
            summary,
            page_num,
            "assignment_lookup_failed",
            "assignment file not found",
        )
        return None

    # Import locally to avoid circular imports
    from scoreform.assignment import load_assignment

    assignment_data = load_assignment(assignment_path)
    if assignment_data is None:
        print(f"Error: Failed to load assignment from {assignment_path}")
        _record_qr_failure(
            summary,
            page_num,
            "assignment_lookup_failed",
            "assignment could not be loaded",
        )
        return None

    return assignment_data


def _question_count_for_assignment(assignment_data, answer_key):
    question_count = assignment_data.get("question_count")
    if (
        not isinstance(question_count, int)
        or question_count < 1
        or question_count > MAX_ASSIGNMENT_QUESTION_COUNT
    ):
        question_count = _infer_question_count(answer_key, default=10)
    return question_count


def _score_qr_aware_image(
    img,
    answer_key,
    page_num,
    debug_dir,
    question_count,
    summary,
    question_start=1,
    layout=None,
):
    result = score_image(
        img,
        answer_key,
        page_num,
        debug_dir=debug_dir,
        question_count=question_count,
        question_start=question_start,
        layout=layout,
    )
    if result is None:
        _record_qr_failure(
            summary,
            page_num,
            "registration_or_scoring_failed",
            "registration/scoring failed",
        )
    return result


def _image_extensions():
    return [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]


def _qr_retained_image_extensions():
    """Return QR-aware image types covered by Core source retention."""
    return [extension for extension in _image_extensions() if extension != ".bmp"]


def _retain_qr_source_scan(file_path, workspace_root, summary):
    try:
        return retain_source_scan(workspace_root, file_path)
    except SourceRetentionError as error:
        print(f"Error: Could not retain source scan before scoring: {error}")
        _record_qr_file_failure(
            summary,
            "source_retention_failed",
            f"Source scan retention failed: {error}",
        )
        return None


def _process_qr_pdf(file_path, all_results, summary, workspace_root=None):
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError
    except ImportError:
        print("Error: The 'pdf2image' module is not installed.")
        print("Please run: pip install pdf2image")
        _record_qr_file_failure(
            summary,
            "pdf2image_missing",
            "pdf2image is not installed",
        )
        return

    print("PDF detected. Converting pages to images...")

    try:
        pages = convert_from_path(file_path)

        for page_num, page in enumerate(pages, start=1):
            print(f"Processing Page {page_num}...")
            _record_qr_processed(summary)

            # Convert PIL image to OpenCV format (RGB to BGR)
            try:
                open_cv_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
            except Exception as e:
                print(f"Error: Could not process image for page {page_num}: {e}")
                _record_qr_failure(
                    summary,
                    page_num,
                    "image_processing_failed",
                    "image loading/processing failed",
                )
                continue

            res = _score_page_qr_aware_with_summary(
                open_cv_image,
                page_num,
                file_path,
                summary,
                workspace_root=workspace_root,
            )
            if res:
                all_results.append(res)

    except PDFInfoNotInstalledError:
        print("Error: Poppler is not installed or not in PATH.")
        print(
            "Please install Poppler and add its 'bin' folder to your system PATH."
        )
        print("Then test with: pdftoppm -h")
        _record_qr_file_failure(
            summary,
            "poppler_missing",
            "Poppler / pdftoppm is not installed or not available in PATH",
        )

    except Exception as e:
        print(f"Error while processing PDF: {e}")
        _record_qr_file_failure(
            summary,
            "pdf_conversion_failed",
            f"PDF conversion/processing failed: {e}",
        )


def _process_qr_image(file_path, all_results, summary, workspace_root=None):
    img = cv2.imread(file_path)

    _record_qr_processed(summary)
    if img is None:
        print(f"Error: Could not read image {file_path}")
        _record_qr_failure(
            summary,
            1,
            "image_processing_failed",
            "image could not be loaded",
        )
        return

    print("Processing Image...")
    res = _score_page_qr_aware_with_summary(
        img,
        page_num=1,
        file_path=file_path,
        summary=summary,
        workspace_root=workspace_root,
    )
    if res:
        all_results.append(res)


def process_file_qr_aware(file_path, workspace_root=None):
    """Process a file with QR-aware scoring.
    
    Decodes QR metadata from each page, loads the corresponding assignment.json,
    scores using the assignment's answer key, and includes metadata in results.
    
    Returns a list of structured results for each successfully scored page,
    or an empty list if no pages were scored successfully.
    """
    migration_pending("QR-aware scan scoring", "#143")

    summary = QRBatchSummary()
    all_results = QRBatchResults(summary=summary)

    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist.")
        _record_qr_file_failure(
            summary,
            "input_file_missing",
            f"Input file not found: {file_path}",
        )
        return all_results

    ext = os.path.splitext(file_path)[1].lower()
    supported = ext == ".pdf" or ext in _qr_retained_image_extensions()
    if not supported:
        print(
            f"Error: Unsupported file extension '{ext}'. "
            "Please provide a PDF or an image."
        )
        _record_qr_file_failure(
            summary,
            "unsupported_input_type",
            f"Unsupported input type: {ext or '(no extension)'}",
        )
        return all_results

    if workspace_root is None:
        workspace_root = workspace.get_scoreform_workspace_root()

    retained_source = _retain_qr_source_scan(file_path, workspace_root, summary)
    if retained_source is None:
        return all_results
    all_results.retained_source = retained_source
    retained_path = os.fspath(retained_source.retained_source_path)

    if ext == ".pdf":
        _process_qr_pdf(
            retained_path,
            all_results,
            summary,
            workspace_root=workspace_root,
        )
    else:
        _process_qr_image(
            retained_path,
            all_results,
            summary,
            workspace_root=workspace_root,
        )

    assembled = _assemble_qr_attempts(all_results, summary)
    all_results.clear()
    all_results.extend(assembled)
    return all_results


def _assemble_qr_attempts(page_results, summary):
    """Assemble successful physical pages into one result per complete attempt."""
    groups = {}
    for result in page_results:
        key = (
            result.get("class_id"),
            result.get("assignment_id"),
            result.get("student_id"),
            result.get("source_file"),
        )
        groups.setdefault(key, []).append(result)

    assembled = []
    for key, pages in groups.items():
        class_id, assignment_id, student_id, source_file = key
        expected_page_count = pages[0]["assignment_page_count"]
        by_page = {}
        duplicate_pages = []
        for page in pages:
            assessment_page = page["assessment_page"]
            if assessment_page in by_page:
                duplicate_pages.append(assessment_page)
            by_page[assessment_page] = page
        missing_pages = sorted(set(range(1, expected_page_count + 1)) - set(by_page))
        if duplicate_pages or missing_pages:
            details = []
            if missing_pages:
                details.append("missing page(s) " + ",".join(map(str, missing_pages)))
            if duplicate_pages:
                details.append(
                    "duplicate page(s) "
                    + ",".join(map(str, sorted(set(duplicate_pages))))
                )
            _record_qr_failure(
                summary,
                None,
                "multi_page_assembly_failed",
                "; ".join(details),
                class_id=class_id,
                assignment_id=assignment_id,
                student_id=student_id,
            )
            continue

        ordered = [by_page[number] for number in range(1, expected_page_count + 1)]
        answers = [answer for page in ordered for answer in page["answers"]]
        assembled.append(
            {
                "page_num": (
                    ordered[0]["page_num"]
                    if len(ordered) == 1
                    else ",".join(str(page["page_num"]) for page in ordered)
                ),
                "score": sum(page["score"] for page in ordered),
                "total_points": pages[0]["assignment_question_count"],
                "answers": answers,
                "class_id": class_id,
                "assignment_id": assignment_id,
                "student_id": student_id,
                "source_file": source_file,
            }
        )
    return assembled


def _score_page_qr_aware(
    img,
    page_num=1,
    file_path=None,
    summary=None,
    workspace_root=None,
):
    """Score a single page with QR-aware metadata extraction.
    
    1. Decode QR metadata from the image.
    2. Locate and load the assignment.json.
    3. Score the page using the assignment's answer key.
    4. Attach metadata to the result.
    
    Returns a scored result dict with metadata, or None on failure.
    """
    migration_pending("QR-aware page scoring", "#143")

    # Step 1: Decode QR metadata
    qr_metadata = _score_page_qr_aware_decode_metadata(
        img,
        page_num,
        summary,
        file_path=file_path,
        workspace_root=workspace_root,
    )
    if qr_metadata is None:
        print(f"Error: Could not decode QR metadata from page {page_num}.")
        return None

    class_id = qr_metadata.get("class_id")
    assignment_id = qr_metadata.get("assignment_id")
    student_id = qr_metadata.get("student_id")
    assessment_page = qr_metadata.get("page")

    print(f"Page {page_num} QR metadata:")
    print(f"  class_id: {class_id}")
    print(f"  assignment_id: {assignment_id}")
    print(f"  student_id: {student_id}")
    print(f"  page: {assessment_page}")

    if not validate_qr_metadata(qr_metadata):
        print(f"Error: QR metadata for page {page_num} is unsafe, rejecting page.")
        _record_qr_failure(
            summary,
            page_num,
            "unsafe_qr",
            "unsafe QR payload",
        )
        return None

    # Step 2: Locate and load assignment.json
    assignment_path = _score_page_qr_aware_assignment_path(
        class_id,
        assignment_id,
        workspace_root=workspace_root,
    )
    assignment_data = _load_qr_aware_assignment(assignment_path, page_num, summary)
    if assignment_data is None:
        if summary is not None and summary.failures:
            failure = summary.failures[-1]
            if failure.page_num == page_num and failure.category == "assignment_lookup_failed":
                failure.class_id = class_id
                failure.assignment_id = assignment_id
                failure.student_id = student_id
        return None

    # Step 3: Extract answer key and score the page
    answer_key = assignment_data.get("answer_key")
    if not answer_key:
        print(f"Error: Assignment {assignment_path} does not contain an answer_key.")
        _record_qr_failure(
            summary,
            page_num,
            "assignment_lookup_failed",
            "assignment missing answer key",
        )
        return None

    question_count = _question_count_for_assignment(assignment_data, answer_key)
    layout = get_layout(assignment_data.get("layout_id"))
    assignment_page_count = page_count_for_question_count(question_count, layout)
    if assessment_page > assignment_page_count:
        reason = (
            f"QR page {assessment_page} is outside assignment page count "
            f"{assignment_page_count}."
        )
        print(f"Error: {reason}")
        _record_qr_failure(
            summary,
            page_num,
            "multi_page_assembly_failed",
            reason,
            class_id=class_id,
            assignment_id=assignment_id,
            student_id=student_id,
        )
        return None
    question_start, _ = question_range_for_page(assessment_page, question_count, layout)
    questions_on_page = question_count_for_page(assessment_page, question_count, layout)

    if workspace_root is None:
        workspace_root = workspace.get_scoreform_workspace_root()
    debug_dir = migration_pending("QR-aware debug routing", "#139 and #143")
    result = _score_qr_aware_image(
        img,
        answer_key,
        page_num,
        debug_dir=debug_dir,
        question_count=questions_on_page,
        summary=summary,
        question_start=question_start,
        layout=layout,
    )
    if result is None:
        if summary is not None and summary.failures:
            failure = summary.failures[-1]
            if (
                failure.page_num == page_num
                and failure.category == "registration_or_scoring_failed"
            ):
                failure.class_id = class_id
                failure.assignment_id = assignment_id
                failure.student_id = student_id
        return None

    # Step 4: Attach metadata to the result
    result["class_id"] = class_id
    result["assignment_id"] = assignment_id
    result["student_id"] = student_id
    result["assessment_page"] = assessment_page
    result["assignment_page_count"] = assignment_page_count
    result["assignment_question_count"] = question_count
    # Attach source file information if provided
    if file_path:
        result["source_file"] = file_path

    return result
