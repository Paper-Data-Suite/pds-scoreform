import os
import cv2
import numpy as np
from scoreform.config import (
    CORNERS,
    CORNER_SIZE,
    DST_PTS,
    IMG_WIDTH,
    IMG_HEIGHT,
    Q_START_Y,
    Q_STEP_Y,
    BOX_SIZE,
    BOX_START_X,
    BOX_STEP_X,
)

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


def score_image(img, answer_key, page_num=1):
    """Scores a single pre-loaded OpenCV image and returns structured data."""
    debug_img = img.copy()

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
    )[1]

    # Find contours
    contours, _ = cv2.findContours(
        thresh,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )

    candidates = []
    for c in contours:
        # Approximate the contour
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)

        # We are looking for squares (4 points)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            aspect_ratio = w / float(h)
            bounding_area = w * h

            if bounding_area == 0:
                continue

            # Compute fill density by counting white pixels in the thresholded image
            # Since threshold is inverted, black marks on white paper become white pixels.
            roi = thresh[y : y + h, x : x + w]
            filled_pixels = cv2.countNonZero(roi)
            fill_density = filled_pixels / float(bounding_area)

            # Filter by area, aspect ratio, and HIGH fill density (solid square)
            if 500 < bounding_area < 20000 and 0.8 <= aspect_ratio <= 1.2:
                if fill_density > 0.7:  # Registration marks are solid (> 70% filled)
                    M = cv2.moments(c)
                    if M["m00"] != 0:
                        cX = int(M["m10"] / M["m00"])
                        cY = int(M["m01"] / M["m00"])
                        candidates.append((cX, cY))

    # Identify the 4 corner marks
    img_h, img_w = img.shape[:2]
    expected_corners = [
        (img_w * 0.1, img_h * 0.1),  # TL
        (img_w * 0.9, img_h * 0.1),  # TR
        (img_w * 0.1, img_h * 0.9),  # BL
        (img_w * 0.9, img_h * 0.9),  # BR
    ]

    corner_centers = []

    for ex_x, ex_y in expected_corners:
        best_candidate = None
        min_dist = float("inf")

        for cX, cY in candidates:
            dist = (cX - ex_x) ** 2 + (cY - ex_y) ** 2
            if dist < min_dist:
                min_dist = dist
                best_candidate = (cX, cY)

        if best_candidate is not None:
            corner_centers.append(best_candidate)

    # Remove duplicates if multiple expected corners mapped to the same candidate
    corner_centers = list(set(corner_centers))

    # Draw debug information on debug_img
    for cX, cY in candidates:
        cv2.circle(debug_img, (cX, cY), 20, (255, 0, 0), 2)  # All candidates in blue

    for cX, cY in corner_centers:
        cv2.circle(debug_img, (cX, cY), 20, (0, 255, 0), 4)  # Selected corners in green

    debug_corners_filename = f"debug_corners_page_{page_num}.png"
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
    for i in range(10):
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

    print(f"\n--- Page {page_num} Final Score: {score}/10 ---")
    for r in results:
        print(f"Q{r['Q']}: {r['Answer']} ({'Correct' if r['Correct'] else 'Wrong'})")

    # Save a debug image
    debug_filename = f"debug_warped_page_{page_num}.png"
    cv2.imwrite(debug_filename, warped)
    print(f"Saved {debug_filename} for visual verification.\n")

    return {
        "page_num": page_num,
        "score": score,
        "total_points": 10,
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
                res = score_image(open_cv_image, answer_key, page_num)
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
        res = score_image(img, answer_key, page_num=1)
        if res:
            res["source_file"] = file_path
            all_results.append(res)

    else:
        print(
            f"Error: Unsupported file extension '{ext}'. "
            "Please provide a PDF or an image."
        )

    return all_results


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


def decode_qr_from_image(img):
    """Decode a QR code from an OpenCV image and parse the OMR1 payload.

    Returns parsed metadata dict or None on failure.
    """
    if img is None:
        print("Error: Provided image is None")
        return None

    detector = cv2.QRCodeDetector()

    try:
        data, points, _ = detector.detectAndDecode(img)
    except Exception as e:
        print(f"Error: Exception while decoding QR: {e}")
        return None

    if not data:
        print("No QR code detected in image.")
        return None

    parsed = parse_qr_payload(data)
    if parsed is None:
        print(f"QR code detected but payload invalid: '{data}'")
        return None

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

    result = score_image(img, answer_key, page_num)
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
