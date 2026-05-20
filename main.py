import cv2
import numpy as np
import sys
import os
import csv
import json
import shutil

# --- Configuration ---

IMG_WIDTH = 1275
IMG_HEIGHT = 1650
CORNER_SIZE = 50

# Corner coordinates (Top-Left, Top-Right, Bottom-Left, Bottom-Right)

CORNERS = [
    (100, 100),
    (IMG_WIDTH - 100 - CORNER_SIZE, 100),
    (100, IMG_HEIGHT - 100 - CORNER_SIZE),
    (IMG_WIDTH - 100 - CORNER_SIZE, IMG_HEIGHT - 100 - CORNER_SIZE),
]

# Centers of the corners for perspective transform (TL, TR, BL, BR)

DST_PTS = np.array(
    [
        [100 + CORNER_SIZE // 2, 100 + CORNER_SIZE // 2],
        [IMG_WIDTH - 100 - CORNER_SIZE // 2, 100 + CORNER_SIZE // 2],
        [100 + CORNER_SIZE // 2, IMG_HEIGHT - 100 - CORNER_SIZE // 2],
        [IMG_WIDTH - 100 - CORNER_SIZE // 2, IMG_HEIGHT - 100 - CORNER_SIZE // 2],
    ],
    dtype="float32",
)

# Question layout

Q_START_Y = 400
Q_STEP_Y = 80
BOX_SIZE = 30
BOX_START_X = 300
BOX_STEP_X = 120

PDF_WIDTH = 612
PDF_HEIGHT = 792
PDF_SCALE = PDF_WIDTH / IMG_WIDTH


def _pdf_coord(x, y):
    """Convert template coordinates to PDF points with origin at bottom-left."""
    return x * PDF_SCALE, PDF_HEIGHT - (y * PDF_SCALE)


def _pdf_rect(c, x, y, w, h, fill=False, stroke=True):
    pd_x, pd_y = _pdf_coord(x, y)
    pd_w = w * PDF_SCALE
    pd_h = h * PDF_SCALE
    c.rect(pd_x, pd_y - pd_h, pd_w, pd_h, fill=fill, stroke=stroke)


def _generate_template_png(filename="template.png"):
    """Generates the blank answer sheet template PNG for debugging."""
    # Create a white image
    img = np.ones((IMG_HEIGHT, IMG_WIDTH, 3), dtype=np.uint8) * 255

    # Draw registration marks (solid black squares)
    for (x, y) in CORNERS:
        cv2.rectangle(
            img,
            (x, y),
            (x + CORNER_SIZE, y + CORNER_SIZE),
            (0, 0, 0),
            -1,
        )

    # Title
    cv2.putText(
        img,
        "Answer Sheet",
        (450, 200),
        cv2.FONT_HERSHEY_SIMPLEX,
        2,
        (0, 0, 0),
        3,
    )

    # Draw questions
    for i in range(10):
        y = Q_START_Y + i * Q_STEP_Y
        cv2.putText(
            img,
            f"{i + 1}.",
            (150, y + 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 0),
            2,
        )

        for j, letter in enumerate(["A", "B", "C", "D"]):
            box_x = BOX_START_X + j * BOX_STEP_X

            # Draw box
            cv2.rectangle(
                img,
                (box_x, y),
                (box_x + BOX_SIZE, y + BOX_SIZE),
                (0, 0, 0),
                2,
            )

            # Draw letter
            cv2.putText(
                img,
                letter,
                (box_x + BOX_SIZE + 15, y + 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 0),
                2,
            )

    cv2.imwrite(filename, img)
    print(f"Debug PNG template saved as {filename}")


def _generate_template_pdf(filename="template.pdf"):
    """Generates a printable letter-size PDF answer sheet."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        print("Error: The 'reportlab' package is required to generate PDF templates.")
        print("Please run: pip install reportlab")
        sys.exit(1)

    c = canvas.Canvas(filename, pagesize=letter)
    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 36)
    title_x, title_y = _pdf_coord(450, 200)
    c.drawString(title_x, title_y, "Answer Sheet")

    # Draw registration marks
    for (x, y) in CORNERS:
        _pdf_rect(c, x, y, CORNER_SIZE, CORNER_SIZE, fill=True)

    c.setLineWidth(1)
    c.setFont("Helvetica", 12)

    # Draw questions
    for i in range(10):
        y = Q_START_Y + i * Q_STEP_Y
        q_x, q_y = _pdf_coord(150, y + 25)
        c.drawString(q_x, q_y, f"{i + 1}.")

        for j, letter in enumerate(["A", "B", "C", "D"]):
            box_x = BOX_START_X + j * BOX_STEP_X
            _pdf_rect(c, box_x, y, BOX_SIZE, BOX_SIZE, fill=False)
            letter_x, letter_y = _pdf_coord(box_x + BOX_SIZE + 15, y + 25)
            c.drawString(letter_x, letter_y, letter)

    c.showPage()
    c.save()
    print(f"Template saved as {filename}")


def generate_template(pdf_filename="template.pdf", png_filename="template.png"):
    """Generates the answer sheet template PDF and an optional PNG debug template."""
    _generate_template_pdf(pdf_filename)
    _generate_template_png(png_filename)


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


def load_answer_key(key_path):
    """Loads and validates the JSON answer key file."""
    if not os.path.exists(key_path):
        print(f"Error: Answer key file '{key_path}' not found.")
        return None

    try:
        with open(key_path, encoding="utf-8") as key_file:
            data = json.load(key_file)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse answer key file '{key_path}': {e}")
        return None
    except Exception as e:
        print(f"Error: Could not read answer key file '{key_path}': {e}")
        return None

    if not isinstance(data, dict):
        print(f"Error: Answer key file '{key_path}' must contain a JSON object.")
        return None

    answer_key = {}
    for key, value in data.items():
        if isinstance(key, str) and key.isdigit():
            q_num = int(key)
        elif isinstance(key, int):
            q_num = key
        else:
            print(
                f"Error: Invalid question number in answer key: {key!r}. "
                "Question numbers must be 1 through 10."
            )
            return None

        if q_num < 1 or q_num > 10:
            print(
                f"Error: Invalid question number '{q_num}' in answer key. "
                "Question numbers must be 1 through 10."
            )
            return None

        if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
            print(
                f"Error: Invalid answer for question {q_num}: {value!r}. "
                "Answers must be A, B, C, or D."
            )
            return None

        answer_key[q_num] = value.strip().upper()

    expected_questions = set(range(1, 11))
    missing_questions = sorted(expected_questions - set(answer_key.keys()))
    extra_questions = sorted(set(answer_key.keys()) - expected_questions)

    if missing_questions or extra_questions:
        if missing_questions:
            print(
                "Error: Answer key is incomplete. "
                f"Missing questions: {', '.join(map(str, missing_questions))}."
            )
        if extra_questions:
            print(
                "Error: Answer key contains invalid question numbers: "
                f"{', '.join(map(str, extra_questions))}."
            )
        return None

    return answer_key


def load_assignment(assignment_path):
    """Loads and validates a richer assignment JSON format."""
    if not os.path.exists(assignment_path):
        print(f"Error: Assignment file '{assignment_path}' not found.")
        return None

    try:
        with open(assignment_path, encoding="utf-8") as assignment_file:
            data = json.load(assignment_file)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse assignment file '{assignment_path}': {e}")
        return None
    except Exception as e:
        print(f"Error: Could not read assignment file '{assignment_path}': {e}")
        return None

    if not isinstance(data, dict):
        print(f"Error: Assignment file '{assignment_path}' must contain a JSON object.")
        return None

    if not isinstance(data.get("assignment_id"), str) or not data["assignment_id"].strip():
        print("Error: 'assignment_id' must be a non-empty string.")
        return None

    if not isinstance(data.get("title"), str) or not data["title"].strip():
        print("Error: 'title' must be a non-empty string.")
        return None

    question_count = data.get("question_count")
    if not isinstance(question_count, int) or not (1 <= question_count <= 15):
        print("Error: 'question_count' must be an integer from 1 to 15.")
        return None

    choices = data.get("choices")
    if choices != ["A", "B", "C", "D"]:
        print("Error: 'choices' must equal exactly ['A', 'B', 'C', 'D'].")
        return None

    answer_key = data.get("answer_key")
    if not isinstance(answer_key, dict):
        print("Error: 'answer_key' must be a JSON object.")
        return None

    if len(answer_key) != question_count:
        print(
            f"Error: 'answer_key' must contain exactly {question_count} entries."
        )
        return None

    normalized_answer_key = {}
    for key, value in answer_key.items():
        if isinstance(key, str) and key.isdigit():
            q_num = int(key)
        elif isinstance(key, int):
            q_num = key
        else:
            print(
                f"Error: Invalid question number in answer_key: {key!r}. "
                f"Question numbers must be 1 through {question_count}."
            )
            return None

        if q_num < 1 or q_num > question_count:
            print(
                f"Error: Invalid question number '{q_num}' in answer_key. "
                f"Question numbers must be 1 through {question_count}."
            )
            return None

        if not isinstance(value, str) or value.strip().upper() not in {"A", "B", "C", "D"}:
            print(
                f"Error: Invalid answer for question {q_num}: {value!r}. "
                "Answers must be A, B, C, or D."
            )
            return None

        normalized_answer_key[q_num] = value.strip().upper()

    missing_questions = sorted(set(range(1, question_count + 1)) - set(normalized_answer_key.keys()))
    if missing_questions:
        print(
            "Error: answer_key is incomplete. "
            f"Missing questions: {', '.join(map(str, missing_questions))}."
        )
        return None

    return {
        "assignment_id": data["assignment_id"].strip(),
        "title": data["title"].strip(),
        "question_count": question_count,
        "choices": ["A", "B", "C", "D"],
        "answer_key": normalized_answer_key,
    }


def load_roster(roster_path):
    """Loads and validates a roster CSV file."""
    if not os.path.exists(roster_path):
        print(f"Error: Roster file '{roster_path}' not found.")
        return None

    try:
        with open(roster_path, encoding="utf-8", newline="") as roster_file:
            reader = csv.DictReader(roster_file)
            if reader.fieldnames is None:
                print(f"Error: Roster file '{roster_path}' is empty or missing headers.")
                return None

            required_columns = {"class_id", "student_id", "last_name", "first_name", "period"}
            header_columns = {column.strip() for column in reader.fieldnames if column is not None}
            if not required_columns.issubset(header_columns):
                missing = required_columns - header_columns
                print(
                    f"Error: Roster file '{roster_path}' is missing required columns: {', '.join(sorted(missing))}."
                )
                return None

            students = []
            class_id_value = None
            seen_student_ids = set()
            row_number = 1

            for row in reader:
                row_number += 1
                normalized = {k.strip(): (v.strip() if v is not None else "") for k, v in row.items()}

                class_id = normalized.get("class_id", "")
                student_id = normalized.get("student_id", "")
                last_name = normalized.get("last_name", "")
                first_name = normalized.get("first_name", "")
                period = normalized.get("period", "")

                if not class_id:
                    print(f"Error: Missing class_id on row {row_number}.")
                    return None
                if not student_id:
                    print(f"Error: Missing student_id on row {row_number}.")
                    return None
                if not last_name:
                    print(f"Error: Missing last_name on row {row_number}.")
                    return None
                if not first_name:
                    print(f"Error: Missing first_name on row {row_number}.")
                    return None
                if not period:
                    print(f"Error: Missing period on row {row_number}.")
                    return None

                if class_id_value is None:
                    class_id_value = class_id
                elif class_id != class_id_value:
                    print(
                        f"Error: Inconsistent class_id on row {row_number}. "
                        f"Expected '{class_id_value}', got '{class_id}'."
                    )
                    return None

                if student_id in seen_student_ids:
                    print(
                        f"Error: Duplicate student_id '{student_id}' found on row {row_number}."
                    )
                    return None

                seen_student_ids.add(student_id)
                students.append(
                    {
                        "class_id": class_id,
                        "student_id": student_id,
                        "last_name": last_name,
                        "first_name": first_name,
                        "period": period,
                    }
                )

    except Exception as e:
        print(f"Error: Could not read roster file '{roster_path}': {e}")
        return None

    if class_id_value is None:
        print(f"Error: Roster file '{roster_path}' contains no student rows.")
        return None

    return {
        "class_id": class_id_value,
        "roster_path": roster_path,
        "students": students,
    }


def setup_assignment_folder(roster_data, assignment_data, roster_path, assignment_path):
    """Create class/assignment folder structure and copy roster/assignment files.

    Returns a dictionary of created paths on success, or None on failure.
    """
    try:
        class_id = roster_data.get("class_id")
        assignment_id = assignment_data.get("assignment_id")

        if not class_id or not assignment_id:
            print("Error: roster_data or assignment_data missing required identifiers.")
            return None

        class_dir = os.path.join("classes", class_id)
        assignments_dir = os.path.join(class_dir, "assignments")
        assignment_dir = os.path.join(assignments_dir, assignment_id)
        templates_dir = os.path.join(assignment_dir, "templates")
        individual_templates_dir = os.path.join(templates_dir, "individual")
        scans_dir = os.path.join(assignment_dir, "scans")
        debug_dir = os.path.join(assignment_dir, "debug")

        # Create directories
        os.makedirs(individual_templates_dir, exist_ok=True)
        os.makedirs(scans_dir, exist_ok=True)
        os.makedirs(debug_dir, exist_ok=True)

        # Copy roster and assignment files
        roster_copy = os.path.join(class_dir, "roster.csv")
        assignment_copy = os.path.join(assignment_dir, "assignment.json")

        # Ensure parent dirs exist for copies
        os.makedirs(class_dir, exist_ok=True)
        os.makedirs(assignment_dir, exist_ok=True)

        shutil.copy2(roster_path, roster_copy)
        shutil.copy2(assignment_path, assignment_copy)

        return {
            "class_dir": class_dir,
            "assignment_dir": assignment_dir,
            "templates_dir": templates_dir,
            "individual_templates_dir": individual_templates_dir,
            "scans_dir": scans_dir,
            "debug_dir": debug_dir,
            "roster_copy": roster_copy,
            "assignment_copy": assignment_copy,
        }

    except Exception as e:
        print(f"Error setting up assignment folder: {e}")
        return None


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
            all_results.append(res)

    else:
        print(
            f"Error: Unsupported file extension '{ext}'. "
            "Please provide a PDF or an image."
        )

    return all_results


def export_to_csv(all_results, output_file):
    """Exports structured scoring data to a CSV file."""
    if not all_results:
        print("No results to export.")
        return

    # Define the CSV headers
    headers = ["Page", "Score", "Total"]
    for i in range(1, 11):
        headers.append(f"Q{i}")
        headers.append(f"Q{i}_Correct")

    try:
        with open(output_file, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=headers)
            writer.writeheader()

            for res in all_results:
                row = {
                    "Page": res["page_num"],
                    "Score": res["score"],
                    "Total": res["total_points"],
                }
                for ans in res["answers"]:
                    q_num = ans["Q"]
                    row[f"Q{q_num}"] = ans["Answer"]
                    row[f"Q{q_num}_Correct"] = ans["Correct"]

                writer.writerow(row)

        print(f"Results successfully exported to {output_file}")
    except Exception as e:
        print(f"Error exporting to CSV: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python main.py generate")
        print("  python main.py score <input_file> [output_csv] [answer_key_json]")
        print("  python main.py validate-assignment <assignment_json>")
        print("  python main.py validate-roster <roster_csv>")
        print("  python main.py setup-assignment <assignment_json> <roster_csv>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "generate":
        generate_template()

    elif cmd == "score":
        if len(sys.argv) < 3:
            print("Please provide the path to the scanned PDF or image.")
            print("Example: python main.py score batch_test.pdf results.csv answer_key.json")
            sys.exit(1)

        input_file = sys.argv[2]
        output_file = "results.csv"
        answer_key_file = "answer_key.json"

        if len(sys.argv) == 4:
            if sys.argv[3].lower().endswith(".json"):
                answer_key_file = sys.argv[3]
            else:
                output_file = sys.argv[3]
        elif len(sys.argv) >= 5:
            output_file = sys.argv[3]
            answer_key_file = sys.argv[4]

        key = load_answer_key(answer_key_file)
        if key is None:
            sys.exit(1)

        # Process the file and get the structured data
        results_data = process_file(input_file, key)

        # Export the collected results to CSV
        if results_data:
            export_to_csv(results_data, output_file)

    elif cmd == "validate-assignment":
        if len(sys.argv) != 3:
            print("Usage: python main.py validate-assignment <assignment_json>")
            sys.exit(1)

        assignment_file = sys.argv[2]
        assignment = load_assignment(assignment_file)
        if assignment is None:
            sys.exit(1)

        print("Assignment file is valid.")
        print(assignment)

    elif cmd == "validate-roster":
        if len(sys.argv) != 3:
            print("Usage: python main.py validate-roster <roster_csv>")
            sys.exit(1)

        roster_file = sys.argv[2]
        roster = load_roster(roster_file)
        if roster is None:
            sys.exit(1)

        print("Roster file is valid.")
        print(f"class_id: {roster['class_id']}")
        print(f"students: {len(roster['students'])}")
        if roster["students"]:
            print("First students:")
            for student in roster["students"][:5]:
                print(
                    f"  {student['student_id']}: {student['last_name']}, {student['first_name']}"
                )

    elif cmd == "setup-assignment":
        if len(sys.argv) != 4:
            print("Usage: python main.py setup-assignment <assignment_json> <roster_csv>")
            sys.exit(1)

        assignment_file = sys.argv[2]
        roster_file = sys.argv[3]

        assignment = load_assignment(assignment_file)
        if assignment is None:
            sys.exit(1)

        roster = load_roster(roster_file)
        if roster is None:
            sys.exit(1)

        setup_paths = setup_assignment_folder(roster, assignment, roster_file, assignment_file)
        if setup_paths is None:
            sys.exit(1)

        print("Assignment folder setup complete.")
        print(f"Class dir: {setup_paths['class_dir']}")
        print(f"Assignment dir: {setup_paths['assignment_dir']}")
        print(f"Roster copy: {setup_paths['roster_copy']}")
        print(f"Assignment copy: {setup_paths['assignment_copy']}")

    else:
        print(f"Unknown command: {cmd}")