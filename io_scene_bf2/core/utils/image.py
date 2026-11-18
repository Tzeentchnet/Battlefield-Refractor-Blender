import numpy as np


def image_to_array(image):
    width, height = image.size
    channels = image.channels
    pixels = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape((height, width, channels))


def array_to_image(image, pixels):
    pixels = np.asarray(pixels, dtype=np.float32)
    width, height = image.size
    expected_shape = (height, width, image.channels)
    if pixels.shape != expected_shape:
        raise ValueError(
            f"Pixel array shape {pixels.shape} does not match image shape {expected_shape}"
        )
    image.pixels.foreach_set(np.ascontiguousarray(pixels).ravel())
    image.update()

