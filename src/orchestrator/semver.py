def is_same_semver(v1: str, v2: str) -> bool:
    """
    Check if two semver versions are the same, supporting a cutoff, meaning,
    if either version lists less subversions than the other, it will be treated
    as equal to the other version up to the number of subversions it lists.

    Examples:
      1.2 == 1.2.0
      1.2 == 1.2.1
      1.2 != 1.3.0
      1.2 != 2.0.0
    """
    v1_parts = v1.split(".")
    v2_parts = v2.split(".")

    return all(v1_parts[i] == v2_parts[i] for i in range(min(len(v1_parts), len(v2_parts))))
