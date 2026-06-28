import cv2
import numpy as np


def preprocess(image_path: str, out_path: str) -> str:
    """
    Enhance image for OCR.
    Pipeline: grayscale → gamma → CLAHE → denoise → upscale if needed.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"cv2 could not read image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Gamma < 1 brightens mid-tones (gray shaded cells) without blowing out whites.
    # This is the key fix for highlighted "best lap" cells.
    gamma = 0.75
    lut = np.array([int((i / 255.0) ** gamma * 255) for i in range(256)], dtype=np.uint8)
    brightened = cv2.LUT(gray, lut)

    # CLAHE with small tiles for localized contrast boost per cell
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(16, 16))
    enhanced = clahe.apply(brightened)

    # Light denoise — h=5 preserves weak text detail in shaded areas
    denoised = cv2.fastNlMeansDenoising(enhanced, h=5)

    # Upscale only if image is small (phone photos are already large enough)
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
