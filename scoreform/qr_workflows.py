"""QR decode command and menu workflow actions."""

import os

import cv2
import numpy as np

from scoreform.migration import migration_pending
from scoreform.scoring import decode_qr_from_image


def run_decode_qr(args):
    """Decode QR metadata from a PDF or image."""
    migration_pending("ScoreForm QR decoding", "#143")

    if len(args) != 1:
        print("Usage: scoreform decode-qr <input_file>")
        return 1

    input_file = args[0]

    if not os.path.exists(input_file):
        print(f"Error: File {input_file} does not exist.")
        return 1

    ext = os.path.splitext(input_file)[1].lower()
    found_any = False
    bad_found = False

    if ext == ".pdf":
        try:
            from pdf2image import convert_from_path
        except ImportError:
            print("Error: The 'pdf2image' module is not installed.\nPlease run: pip install pdf2image")
            return 1

        try:
            pages = convert_from_path(input_file)
        except Exception as e:
            print(f"Error while converting PDF: {e}")
            return 1

        for page_num, page in enumerate(pages, start=1):
            open_cv_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)
            print(f"Page {page_num} QR:")
            parsed = decode_qr_from_image(open_cv_image)
            if parsed:
                found_any = True
                print(f"  class_id: {parsed.get('class_id')}")
                print(f"  assignment_id: {parsed.get('assignment_id')}")
                print(f"  student_id: {parsed.get('student_id')}")
            else:
                bad_found = True
                print(f"  No valid QR decoded on page {page_num}.")

    elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]:
        img = cv2.imread(input_file)
        if img is None:
            print(f"Error: Could not read image {input_file}")
            return 1

        parsed = decode_qr_from_image(img)
        if parsed:
            found_any = True
            print("Decoded QR:")
            print(f"  class_id: {parsed.get('class_id')}")
            print(f"  assignment_id: {parsed.get('assignment_id')}")
            print(f"  student_id: {parsed.get('student_id')}")
        else:
            print("No valid QR decoded from image.")
            return 1

    else:
        print(f"Error: Unsupported file extension '{ext}'. Please provide a PDF or an image.")
        return 1

    if not found_any:
        print("Error: No QR code could be decoded from any page or image.")
        return 1

    if bad_found:
        print("Error: At least one page contained an unreadable or malformed QR payload.")
        return 1

    return 0
