"""Every character has at least one stat of 1 or more (sheet.validate)."""


def hook(view, params, rng):
    if view["kind"] != "pc":
        return []
    if max(view["stats"].values()) < 1:
        return ["needs at least one stat of 1 or more"]
    return []
