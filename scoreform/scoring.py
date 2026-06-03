import os
import cv2
import numpy as np
from scoreform.config import (
    CORNER_SIZE,
    DST_PTS,
    IMG_WIDTH,
    IMG_HEIGHT,
    Q_START_Y,
    Q_STEP_Y,
    BOX_SIZE,
    BOX_START_X,
    BOX_STEP_X,
    LOCAL_DEBUG_DIR,
    MAX_QUESTION_COUNT,
)
from scoreform.validation import IDENTIFIER_PATTERN, is_safe_identifier, validate_identifier


CORNER_ZONE_FRACTION = 0.22
MIN_REGISTRATION_SIZE_RATIO = 0.65
MAX_REGISTRATION_SIZE_RATIO = 4.0


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
    if max_question > MAX_QUESTION_COUNT:
        return default

    if set(keys) == set(range(1, max_question + 1)):
        return max_question
    return default


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


def _registration_size_bounds(img_w, img_h):
    scale = min(img_w / IMG_WIDTH, img_h / IMG_HEIGHT)
    expected_size = CORNER_SIZE * scale
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


def _find_registration_mark_centers(thresh, img_w, img_h):
    """Find registration mark centers using per-corner dark-component searches."""
    min_size, max_size, expected_size = _registration_size_bounds(img_w, img_h)
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


def score_image(img, answer_key, page_num=1, debug_dir=None, question_count=None):
    """Scores a single pre-loaded OpenCV image and returns structured data."""
    if debug_dir is None:
        debug_dir = LOCAL_DEBUG_DIR

    debug_img = img.copy()
    if question_count is None:
        question_count = _infer_question_count(answer_key, default=10)

    if not isinstance(question_count, int) or question_count < 1:
        question_count = 10

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]

    img_h, img_w = img.shape[:2]
    candidates, corner_centers = _find_registration_mark_centers(thresh, img_w, img_h)

    # Draw debug information on debug_img
    for cX, cY in candidates:
        cv2.circle(debug_img, (cX, cY), 20, (255, 0, 0), 2)  # All candidates in blue

    for cX, cY in corner_centers:
        cv2.circle(debug_img, (cX, cY), 20, (0, 255, 0), 4)  # Selected corners in green

    debug_corners_filename = f"debug_corners_page_{page_num}.png"
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        debug_corners_filename = os.path.join(debug_dir, debug_corners_filename)
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
    M = cv2.getPerspectiveTransform(rect, DST_PTS)
    warped = cv2.warpPerspective(img, M, (IMG_WIDTH, IMG_HEIGHT))

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
    for i in range(question_count):
        y = Q_START_Y + i * Q_STEP_Y

        row_filled = []

        for j, letter in enumerate(["A", "B", "C", "D"]):
            box_x = BOX_START_X + j * BOX_STEP_X

            # Extract ROI for the box.
            # Inset avoids counting the black border of the box itself.
            inset = 5
            roi = warped_thresh[
                y + inset : y + BOX_SIZE - inset,
                box_x + inset : box_x + BOX_SIZE - inset,
            ]

            # Count white pixels (filled area)
            filled_pixels = cv2.countNonZero(roi)
            total_pixels = roi.shape[0] * roi.shape[1]
            fill_ratio = filled_pixels / total_pixels
            row_filled.append((fill_ratio, letter))

        # Determine the chosen answer
        row_filled.sort(reverse=True, key=lambda x: x[0])

        best_fill, best_letter = row_filled[0]
        second_fill, _ = row_filled[1]

        # Thresholds: a box needs at least 30% fill to be considered marked.
        if best_fill > 0.3:
            # Check for ambiguity (two boxes filled)
            if second_fill > 0.3 and (best_fill - second_fill < 0.2):
                answer = "AMBIGUOUS"
            else:
                answer = best_letter
        else:
            answer = "BLANK"

        # Score it
        correct = False
        if answer == answer_key.get(i + 1, ""):
            score += 1
            correct = True

        results.append(
            {
                "Q": i + 1,
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
    Returns a list of structured results for each successfully scored page."""

    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist.")
        return []

    ext = os.path.splitext(file_path)[1].lower()
    all_results = []

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError
        except ImportError:
            print("Error: The 'pdf2image' module is not installed.")
            print("Please run: pip install pdf2image")
            return []

        print("PDF detected. Converting pages to images...")

        try:
            pages = convert_from_path(file_path)

            for page_num, page in enumerate(pages, start=1):
                print(f"Scoring Page {page_num}...")

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

        except PDFInfoNotInstalledError:
            print("Error: Poppler is not installed or not in PATH.")
            print(
                "Please install Poppler and add its 'bin' folder to your system PATH."
            )
            print("Then test with: pdftoppm -h")

        except Exception as e:
            print(f"Error while processing PDF: {e}")

    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        img = cv2.imread(file_path)

        if img is None:
            print(f"Error: Could not read image {file_path}")
            return []

        print(f"Scoring Image...")
        res = score_image(
            img,
            answer_key,
            page_num=1,
            question_count=_infer_question_count(answer_key, default=10),
        )
        if res:
            res["source_file"] = file_path
            all_results.append(res)

    else:
        print(
            f"Error: Unsupported file extension '{ext}'. "
            "Please provide a PDF or an image."
        )

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

    for field in ["class_id", "assignment_id", "student_id"]:
        if field not in qr_metadata:
            print(f"Error: QR metadata missing required field '{field}'.")
            return False
        if not validate_qr_identifier(field, qr_metadata[field]):
            return False

    return True


def parse_qr_payload(payload):
    """Parse an OMR1 QR payload string and return metadata dict or None.

    Expected format:
      OMR1|class=<class_id>|aid=<assignment_id>|sid=<student_id>
    """
    if payload is None:
        print("Error: QR payload is None")
        return None

    payload = payload.strip()

    if not payload:
        print("Error: QR payload is empty")
        return None

    parts = payload.split("|")

    if len(parts) < 4:
        print(f"Error: QR payload malformed: '{payload}'")
        return None

    if parts[0] != "OMR1":
        print(f"Error: QR payload missing OMR1 header: '{payload}'")
        return None

    kv = {}
    for p in parts[1:]:
        if "=" not in p:
            print(f"Error: QR payload part malformed: '{p}' in '{payload}'")
            return None
        k, v = p.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not v:
            print(f"Error: QR payload key '{k}' has empty value in '{payload}'")
            return None
        kv[k] = v

    required = {"class": "class_id", "aid": "assignment_id", "sid": "student_id"}
    out = {}
    for src, dst in required.items():
        if src not in kv:
            print(f"Error: QR payload missing required key '{src}' in '{payload}'")
            return None
        out[dst] = kv[src]

    return out


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


def _expected_qr_crops(img):
    """Yield generous upper-right crops around the template QR location."""
    h, w = img.shape[:2]
    crop_bounds = [
        (0.58, 0.00, 1.00, 0.38),
        (0.50, 0.00, 1.00, 0.48),
        (0.65, 0.04, 0.98, 0.30),
    ]

    for x1f, y1f, x2f, y2f in crop_bounds:
        x1 = max(0, int(w * x1f))
        y1 = max(0, int(h * y1f))
        x2 = min(w, int(w * x2f))
        y2 = min(h, int(h * y2f))
        if x2 > x1 and y2 > y1:
            yield img[y1:y2, x1:x2]


def _qr_candidate_images(img):
    for label, candidate in _qr_preprocess_attempts(img):
        yield label, candidate

    for crop_index, crop in enumerate(_expected_qr_crops(img), start=1):
        for label, candidate in _qr_preprocess_attempts(crop):
            yield f"crop {crop_index} {label}", candidate


def decode_qr_from_image(img):
    """Decode a QR code from an OpenCV image and parse the OMR1 payload.

    Returns parsed metadata dict or None on failure.
    """
    if img is None:
        print("Error: Provided image is None")
        return None

    detector = cv2.QRCodeDetector()

    data = None
    success_label = None

    for label, candidate in _qr_candidate_images(img):
        try:
            data = _try_decode_qr(detector, candidate)
        except Exception as e:
            print(f"Error: Exception while decoding QR: {e}")
            return None
        if data:
            success_label = label
            break

    if not data:
        print("No QR code detected after raw/preprocessed decode attempts.")
        return None

    parsed = parse_qr_payload(data)
    if parsed is None:
        print(f"QR code detected but payload invalid: '{data}'")
        return None

    if not validate_qr_metadata(parsed):
        print(f"QR code payload failed validation: '{data}'")
        return None

    if success_label != "raw":
        print(f"QR decoded using {success_label} fallback.")

    return parsed


def process_file_qr_aware(file_path):
    """Process a file with QR-aware scoring.
    
    Decodes QR metadata from each page, loads the corresponding assignment.json,
    scores using the assignment's answer key, and includes metadata in results.
    
    Returns a list of structured results for each successfully scored page,
    or an empty list if no pages were scored successfully.
    """
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist.")
        return []

    ext = os.path.splitext(file_path)[1].lower()
    all_results = []

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError
        except ImportError:
            print("Error: The 'pdf2image' module is not installed.")
            print("Please run: pip install pdf2image")
            return []

        print("PDF detected. Converting pages to images...")

        try:
            pages = convert_from_path(file_path)

            for page_num, page in enumerate(pages, start=1):
                print(f"Processing Page {page_num}...")

                # Convert PIL image to OpenCV format (RGB to BGR)
                open_cv_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
                res = _score_page_qr_aware(open_cv_image, page_num, file_path)
                if res:
                    all_results.append(res)

        except PDFInfoNotInstalledError:
            print("Error: Poppler is not installed or not in PATH.")
            print(
                "Please install Poppler and add its 'bin' folder to your system PATH."
            )
            print("Then test with: pdftoppm -h")

        except Exception as e:
            print(f"Error while processing PDF: {e}")

    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        img = cv2.imread(file_path)

        if img is None:
            print(f"Error: Could not read image {file_path}")
            return []

        print("Processing Image...")
        res = _score_page_qr_aware(img, page_num=1, file_path=file_path)
        if res:
            all_results.append(res)

    else:
        print(
            f"Error: Unsupported file extension '{ext}'. "
            "Please provide a PDF or an image."
        )

    return all_results


def _score_page_qr_aware(img, page_num=1, file_path=None):
    """Score a single page with QR-aware metadata extraction.
    
    1. Decode QR metadata from the image.
    2. Locate and load the assignment.json.
    3. Score the page using the assignment's answer key.
    4. Attach metadata to the result.
    
    Returns a scored result dict with metadata, or None on failure.
    """
    # Step 1: Decode QR metadata
    qr_metadata = decode_qr_from_image(img)
    if qr_metadata is None:
        print(f"Error: Could not decode QR metadata from page {page_num}.")
        return None

    class_id = qr_metadata.get("class_id")
    assignment_id = qr_metadata.get("assignment_id")
    student_id = qr_metadata.get("student_id")

    print(f"Page {page_num} QR metadata:")
    print(f"  class_id: {class_id}")
    print(f"  assignment_id: {assignment_id}")
    print(f"  student_id: {student_id}")

    if not validate_qr_metadata(qr_metadata):
        print(f"Error: QR metadata for page {page_num} is unsafe, rejecting page.")
        return None

    # Step 2: Locate and load assignment.json
    assignment_path = os.path.join(
        "classes",
        class_id,
        "assignments",
        assignment_id,
        "assignment.json",
    )

    if not os.path.exists(assignment_path):
        print(f"Error: Assignment file not found: {assignment_path}")
        return None

    # Import locally to avoid circular imports
    from scoreform.assignment import load_assignment

    assignment_data = load_assignment(assignment_path)
    if assignment_data is None:
        print(f"Error: Failed to load assignment from {assignment_path}")
        return None

    # Step 3: Extract answer key and score the page
    answer_key = assignment_data.get("answer_key")
    if not answer_key:
        print(f"Error: Assignment {assignment_path} does not contain an answer_key.")
        return None

    question_count = assignment_data.get("question_count")
    if not isinstance(question_count, int) or question_count < 1 or question_count > MAX_QUESTION_COUNT:
        question_count = _infer_question_count(answer_key, default=10)

    debug_dir = os.path.join(
        "classes",
        class_id,
        "assignments",
        assignment_id,
        "debug",
    )
    result = score_image(
        img,
        answer_key,
        page_num,
        debug_dir=debug_dir,
        question_count=question_count,
    )
    if result is None:
        return None

    # Step 4: Attach metadata to the result
    result["class_id"] = class_id
    result["assignment_id"] = assignment_id
    result["student_id"] = student_id
    # Attach source file information if provided
    if file_path:
        result["source_file"] = file_path

    return result
