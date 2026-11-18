from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, Iterator, TypeVar


T = TypeVar("T")


class PackingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PackedRectangle(Generic[T]):
    x: int
    y: int
    width: int
    height: int
    rid: T


@dataclass(frozen=True, slots=True)
class PackedBin(Generic[T]):
    width: int
    height: int
    rectangles: tuple[PackedRectangle[T], ...]

    def __iter__(self) -> Iterator[PackedRectangle[T]]:
        return iter(self.rectangles)

    def __len__(self):
        return len(self.rectangles)


@dataclass(frozen=True, slots=True)
class _FreeRectangle:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self):
        return self.x + self.width

    @property
    def top(self):
        return self.y + self.height


class _BinState(Generic[T]):
    def __init__(self, width, height, allow_rotation):
        self.width = width
        self.height = height
        self.allow_rotation = allow_rotation
        self.free_rectangles = [_FreeRectangle(0, 0, width, height)]
        self.rectangles = []

    def find_position(self, width, height):
        best = None
        orientations = ((width, height),)
        if self.allow_rotation and width != height:
            orientations += ((height, width),)

        for free_index, free in enumerate(self.free_rectangles):
            for packed_width, packed_height in orientations:
                if packed_width > free.width or packed_height > free.height:
                    continue
                remaining_width = free.width - packed_width
                remaining_height = free.height - packed_height
                score = (
                    min(remaining_width, remaining_height),
                    max(remaining_width, remaining_height),
                    free.width * free.height - packed_width * packed_height,
                    free.y,
                    free.x,
                    free_index,
                )
                candidate = (
                    score,
                    free.x,
                    free.y,
                    packed_width,
                    packed_height,
                )
                if best is None or candidate[0] < best[0]:
                    best = candidate
        return best

    def place(self, position, rid):
        _, x, y, width, height = position
        placed = PackedRectangle(x, y, width, height, rid)
        self._split_free_rectangles(placed)
        self.rectangles.append(placed)
        return placed

    def _split_free_rectangles(self, placed):
        split = []
        for free in self.free_rectangles:
            if (
                placed.x >= free.right
                or placed.x + placed.width <= free.x
                or placed.y >= free.top
                or placed.y + placed.height <= free.y
            ):
                split.append(free)
                continue

            if placed.x > free.x:
                split.append(
                    _FreeRectangle(
                        free.x,
                        free.y,
                        placed.x - free.x,
                        free.height,
                    )
                )
            if placed.x + placed.width < free.right:
                split.append(
                    _FreeRectangle(
                        placed.x + placed.width,
                        free.y,
                        free.right - (placed.x + placed.width),
                        free.height,
                    )
                )
            if placed.y > free.y:
                split.append(
                    _FreeRectangle(
                        free.x,
                        free.y,
                        free.width,
                        placed.y - free.y,
                    )
                )
            if placed.y + placed.height < free.top:
                split.append(
                    _FreeRectangle(
                        free.x,
                        placed.y + placed.height,
                        free.width,
                        free.top - (placed.y + placed.height),
                    )
                )

        self.free_rectangles = _remove_contained(split)

    def freeze(self):
        return PackedBin(self.width, self.height, tuple(self.rectangles))


def pack_rectangles(
    rectangles: Iterable[tuple[int, int, T]],
    bin_size: tuple[int, int],
    *,
    max_bins=1,
    allow_rotation=False,
):
    width, height = _validate_size(bin_size, "Bin")
    if max_bins < 1:
        raise ValueError("max_bins must be at least 1")

    pending = []
    for order, (rect_width, rect_height, rid) in enumerate(rectangles):
        rect_width, rect_height = _validate_size(
            (rect_width, rect_height),
            f"Rectangle {rid!r}",
        )
        if (
            (rect_width > width or rect_height > height)
            and (
                not allow_rotation
                or rect_height > width
                or rect_width > height
            )
        ):
            raise PackingError(
                f"Rectangle {rid!r} ({rect_width}x{rect_height}) does not fit "
                f"in a {width}x{height} bin"
            )
        pending.append((rect_width, rect_height, rid, order))

    pending.sort(
        key=lambda item: (
            -(item[0] * item[1]),
            -max(item[0], item[1]),
            -min(item[0], item[1]),
            item[3],
        )
    )

    bins: list[_BinState[T]] = []
    for rect_width, rect_height, rid, _ in pending:
        best = None
        for bin_index, bin_state in enumerate(bins):
            position = bin_state.find_position(rect_width, rect_height)
            if position is None:
                continue
            candidate = (position[0] + (bin_index,), bin_state, position)
            if best is None or candidate[0] < best[0]:
                best = candidate

        if best is None:
            if len(bins) >= max_bins:
                raise PackingError(
                    f"Rectangle {rid!r} could not be packed into {max_bins} "
                    f"{width}x{height} bin(s)"
                )
            bin_state = _BinState(width, height, allow_rotation)
            bins.append(bin_state)
            position = bin_state.find_position(rect_width, rect_height)
            if position is None:
                raise PackingError(
                    f"Rectangle {rid!r} ({rect_width}x{rect_height}) does not fit "
                    f"in a {width}x{height} bin"
                )
        else:
            _, bin_state, position = best

        bin_state.place(position, rid)

    return [bin_state.freeze() for bin_state in bins]


def pack_rectangles_power_of_two(rectangles, *, allow_rotation=False):
    rectangles = list(rectangles)
    if not rectangles:
        raise ValueError("At least one rectangle is required")

    validated = [
        (*_validate_size((width, height), f"Rectangle {rid!r}"), rid)
        for width, height, rid in rectangles
    ]
    required_area = sum(width * height for width, height, _ in validated)
    min_width = _next_power_of_two(max(width for width, _, _ in validated))
    min_height = _next_power_of_two(max(height for _, height, _ in validated))
    max_width = _next_power_of_two(sum(width for width, _, _ in validated))
    max_height = _next_power_of_two(sum(height for _, height, _ in validated))

    candidates = [
        (width, height)
        for width in _powers_of_two(min_width, max_width)
        for height in _powers_of_two(min_height, max_height)
        if width * height >= required_area
    ]
    candidates.sort(
        key=lambda size: (
            size[0] * size[1],
            max(size),
            abs(size[0] - size[1]),
            size[0],
        )
    )

    for size in candidates:
        try:
            return pack_rectangles(
                validated,
                size,
                max_bins=1,
                allow_rotation=allow_rotation,
            )[0]
        except PackingError:
            continue

    raise PackingError("Unable to find a power-of-two bin for the rectangles")


def _validate_size(size, label):
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError(f"{label} dimensions must be integers")
    if width <= 0 or height <= 0:
        raise ValueError(f"{label} dimensions must be positive")
    return width, height


def _remove_contained(rectangles):
    unique = list(dict.fromkeys(rectangles))
    contained = set()
    for index, first in enumerate(unique):
        if first in contained:
            continue
        for other_index, second in enumerate(unique):
            if index == other_index or second in contained:
                continue
            if (
                first.x <= second.x
                and first.y <= second.y
                and first.right >= second.right
                and first.top >= second.top
            ):
                contained.add(second)
    return [rectangle for rectangle in unique if rectangle not in contained]


def _next_power_of_two(value):
    return 1 << (value - 1).bit_length()


def _powers_of_two(first, last):
    value = first
    while value <= last:
        yield value
        value <<= 1

