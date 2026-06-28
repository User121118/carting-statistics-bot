import cv2
import numpy as np


def preprocess(image_path: str, out_path: str) -> str:
    """
    Enhance image for OCR: grayscale, contrast boost, denoise.
    Returns out_path.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"cv2 could not read image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Smaller tiles = more local contrast boost → helps darkened/shaded cells
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
    enhanced = clahe.apply(gray)

    # Light denoise only — aggressive denoising blurs low-contrast text
    denoised = cv2.fastNlMeansDenoising(enhanced, h=5)

    # Scale up small images so OCR has more pixels to work with
    h, w = denoised.shape[:2]
    if w < 1500:
        scale = 1500 / w
        denoised = cv2.resize(
            denoised,
            (int(w * scale), int(h * scale)),
            interpolation=cv2.INTER_CUBIC,
        )

    cv2.imwrite(out_path, denoised)
    return out_path
