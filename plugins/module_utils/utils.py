import os.path
import base64
import mimetypes
from typing import *

import requests
from ansible.errors import AnsibleError


class ImageError(AnsibleError):
    def __init__(self, message=""):
        super(ImageError, self).__init__(message=message)


def detect_mime_type(file: str, default: Optional[str] = None) -> str:
    mime = mimetypes.guess_type(file)[0]
    if not mime:
        mime = default
    return mime


def file2data(file: str, mime: Optional[str] = None) -> str:
    mime_type = detect_mime_type(file, mime)

    if not mime_type.__contains__("image"):
        raise ImageError("File {} has mime type {} which is not image".format(file, mime_type))

    base64image = "data:{};charset=utf-8;base64,".format(mime_type)

    with open(file, "rb") as image_file:
        base64image += base64.b64encode(image_file.read()).decode('utf-8')

    print(base64image)

    return base64image


def url2file(url: str) -> (str, str):
    r = requests.get(url)
    mime = r.headers['content-type']
    file_suffix = ""
    if "jpeg" in mime:
        file_suffix = ".jpeg"
    elif "png" in mime:
        file_suffix = ".png"
    elif "svg" in mime:
        file_suffix = ".svg"
    file = '/Users/klaus/Downloads/' + url.split("/").pop() + file_suffix
    with open(file, 'wb') as f:
        f.write(r.content)

    return file, r.headers['content-type']


def url2data(url: str) -> str:
    (file, mime) = url2file(url)
    return file2data(file, mime)


def image2data(image: str) -> str:
    if image.startswith("data"):
        return image
    elif image.startswith("http"):
        return url2data(image)
    else:
        if os.path.isfile(image):
            f = open(image)
            f.close()
            return file2data(image)
        else:
            raise FileNotFoundError(image)
