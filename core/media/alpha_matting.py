"""Lazy optional edge refinement shared by image and video background removal."""


def refine_alpha_edges(image, mask):
    """Solve a narrow uncertain band and recover uncontaminated foreground RGB."""
    from rembg.bg import alpha_matting_cutout

    return alpha_matting_cutout(image, mask, 240, 10, 5).convert("RGBA")


def pad_transparent_rgb(image):
    """Prevent 4:2:0 video chroma from mixing hidden screen RGB into visible edges."""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import distance_transform_edt

    rgba = np.asarray(image.convert("RGBA")).copy()
    alpha = rgba[..., 3]
    if not np.any(alpha >= 64):
        return image
    distance, nearest = distance_transform_edt(alpha < 64, return_indices=True)
    edge = (alpha < 4) & (distance <= 3)
    rgba[edge, :3] = rgba[nearest[0][edge], nearest[1][edge], :3]
    rgba[(alpha < 4) & ~edge, :3] = 0
    return Image.fromarray(rgba, "RGBA")
