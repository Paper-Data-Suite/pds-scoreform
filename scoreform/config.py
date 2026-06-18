import os

import numpy as np

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
MAX_QUESTION_COUNT = 15
Q_START_Y = 400
Q_STEP_Y = 80
BOX_SIZE = 30
BOX_START_X = 300
BOX_STEP_X = 120

PDF_WIDTH = 612
PDF_HEIGHT = 792
PDF_SCALE = PDF_WIDTH / IMG_WIDTH

# Local generated artifacts used by generic/manual development workflows.
LOCAL_OUTPUTS_DIR = "local_outputs"
LOCAL_TEMPLATES_DIR = os.path.join(LOCAL_OUTPUTS_DIR, "templates")
LOCAL_RESULTS_DIR = os.path.join(LOCAL_OUTPUTS_DIR, "results")
LOCAL_DEBUG_DIR = os.path.join(LOCAL_OUTPUTS_DIR, "debug")
LOCAL_TEMP_DIR = os.path.join(LOCAL_OUTPUTS_DIR, "temp")
LOCAL_TEMPLATE_PDF = os.path.join(LOCAL_TEMPLATES_DIR, "template.pdf")
LOCAL_TEMPLATE_PNG = os.path.join(LOCAL_TEMPLATES_DIR, "template.png")
LOCAL_RESULTS_CSV = os.path.join(LOCAL_RESULTS_DIR, "results.csv")

# Developer-only opt-in for retaining full-page QR failure diagnostics.
FULL_PAGE_DIAGNOSTICS_ENV = "PDS_SCOREFORM_FULL_PAGE_DIAGNOSTICS"
