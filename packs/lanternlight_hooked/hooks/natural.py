"""A natural 20 always passes; a natural 1 always fails (resolution.step)."""


def hook(view, params, rng):
    faces = [face for group in view["dice"] for face in group["rolls"]]
    if len(faces) != 1:
        return None
    if faces[0] == 20:
        return {"outcome": view["scale"][-1]}
    if faces[0] == 1:
        return {"outcome": view["scale"][0]}
    return None
