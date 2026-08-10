import cv2
import numpy as np
from ddddocr import DdddOcr

ocr = DdddOcr(show_ad=False)


def fuck_captcha(captcha_img: bytes) -> str:
    """识别验证码"""
    img = cv2.imdecode(np.frombuffer(captcha_img, np.uint8), cv2.IMREAD_GRAYSCALE)

    _, img = cv2.threshold(img, 190, 255, cv2.THRESH_BINARY)
    img = cv2.bitwise_not(img)

    _, img_data = cv2.imencode(".png", img)
    code = ocr.classification(img_data.tobytes())

    return code
