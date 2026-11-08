import random
import time
import sys
from collections.abc import Generator
from collections import defaultdict
from dataclasses import dataclass

from pacn.pac_logger import logging
from pacn.multiverse import Multiverse
from pacn.universe import RGBUniverse
from pacn.colors import get_rgb
from pacn.utils import DEFAULT_CID_BYTES

simulation = False
# IP addresses
PIXEL_CONTROLLER1 = "192.168.1.20"
PIXEL_CONTROLLER2 = "192.168.1.21"
LOOPBACK = "127.0.0.1"

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
del logging

class Ropelight:
    """
    Represents a 250-pixel rope light.  This light string
    requires two E1.31 Universes, numbered consecutively.
    The argument to the constructor is the number of the first
    of those universes."""
    def __init__(self, n_uni0: int, n_uni1=-1) -> None:
        uni1 = n_uni1 if n_uni1 > 0 else n_uni0+1
        ip = LOOPBACK if simulation else PIXEL_CONTROLLER1
        self.uni0 = RGBUniverse(DEFAULT_CID_BYTES, n_uni0, ip, 170)
        self.uni1 = RGBUniverse(DEFAULT_CID_BYTES, uni1, ip, 80)
        self.rope = ['black'] * 250

    def update(self) -> None:
        self.uni0.set_pixel_data(self.rope[:170])
        self.uni1.set_pixel_data(self.rope[170:])

@dataclass
class RiverParameters:
    # pylint: disable=too-many-positional-arguments
    def __init__(self, wavelength: float, phase: float, rate: float,
            rgb_max: str, rgb_min: str) -> None:
        self.wavelength = wavelength # a number of pixels
        self.phase = phase # a number of pixels
        self.rate = rate # pixels/tick of the Multiverse clock (<1 typically)
        self.rgb_max = get_rgb(rgb_max) # r, g, b tuple
        self.rgb_min = get_rgb(rgb_min) # r, g, b tuple
        self.hw = wavelength * 0.5   # half-width
        self.rgb_range = [a-b for a, b in zip(self.rgb_max, self.rgb_min)]

    def color(self, pix: int) -> str:
        """Return a color string for pixel # pixno"""
        phase = (pix + self.phase) % self.wavelength
        # phase ranges between 0 and 2 * width
        fraction = abs(self.hw - phase) / self.hw
        # fraction ranges from 0 to 1
        x = [int(fraction*a+b+0.5) for a, b in 
                        zip(self.rgb_range, self.rgb_min)]
        color = ''.join([format(a, "02x") for a in x])
        return f"#{color}"

class RiverStringBase(Ropelight):
    def __init__(self, n_uni0: int, params: RiverParameters) -> None:
        super().__init__(n_uni0)
        self.params = params
        self.pixels: list[str] = []
        self.move = 0.0
        self.next_pix = 250
        self._initialize()

    def _initialize(self) -> None:
        for n in range(249, -1, -1):
            self.pixels.append(self.params.color(n))

    def step(self) -> bool:
        """Returns true if the waves moved."""
        self.move += self.params.rate
        moved = False
        while self.move > 1.0:
            self.move -= 1.0
            self.pixels = [self.params.color(self.next_pix)] + self.pixels[:-1]
            self.next_pix += 1
            moved = True
        return moved

    def copy_waves(self) -> None:
        self.rope = self.pixels[:250]

    def add_floater(self, f: Floater) -> None:
        # Replace background pixels by floater pixels
        # Handle cases where the floater partially overlaps the string ends
        # f.n is the current index of the floater
        f0 = 0
        f1 = len(f.pixels)
        # pix0, pix1 is the slice range to replace
        pix0 = f.n - f1
        pix1 = f.n
        if pix1 > 250:
            if pix0 > 249:
                f.finished = True
                return
            f1 = 250 - pix1
            pix1 = 250
        elif pix0 < 0:
            f0 = -pix0
            pix0 = 0
        self.rope[pix0:pix1] = f.pixels[f0:f1]

class Floater:
    COLORS = ('red', 'yellow', 'green', 'cyan', 'magenta', 'white')
    def __init__(self, string: int, color: str, length: int, 
                 rate: float) -> None:
        self.string = string
        self.rate = rate
        self.pixels: list[str] = []
        self.n = 0
        self.move = 0.0
        self.finished = False
        self._initialize(color, length)

    def _initialize(self, color: str, length: int) -> None:
        rgb = get_rgb(color)
        for n in range(length):
            f = n / (length - 1)
            x = [int(f*a) for a in rgb]
            color = ''.join([format(a, "02x") for a in x])
            self.pixels.append(f"#{color}")

    def step(self) -> bool:
        moved = False
        self.move += self.rate
        while self.move > 1.0:
            self.move -= 1.0
            self.n += 1
            moved = True
        return moved

class River:
    def __init__(self) -> None:
        self.bases: list[RiverStringBase] = []
        self.floaters: dict[int, set[Floater]] = defaultdict(set)
        self._init_bases()

    def _init_bases(self) -> None:
        def make_parameters() -> Generator[RiverParameters]:
            yield RiverParameters(30.0, 0.0, 0.3, '#80ffff', '#000080')
            yield RiverParameters(20.0, 10.0, 0.25, '#80ffff', '#000080')
            yield RiverParameters(30.0, 10.0, 0.2, '#80ffff', '#000080')
            yield RiverParameters(30.0, 20.0, 0.2, '#80ffff', '#000080')
            yield RiverParameters(40.0, 5.0, 0.25, '#80ffff', '#000080')
            yield RiverParameters(30.0, 20.0, 0.3, '#80ffff', '#000080')
        first_uni = 9
        for n, rp in enumerate(make_parameters()):
            self.bases.append(RiverStringBase(first_uni+n*2, rp))

    def initialize(self, mv: Multiverse) -> None:
        for base in self.bases:
            mv.add_universe(base.uni0)
            mv.add_universe(base.uni1)

    def floater_count(self) -> int:
        return sum(len(a) for a in self.floaters.values())

    def step(self, _t: float) -> None:
        bx: list[bool] = []
        for base in self.bases:
            if base.step():
                bx.append(True)
            else:
                bx.append(False)
        for n, floaters in self.floaters.items():
            for floater in floaters.copy():
                if floater.step():
                    bx[n] = True
                if floater.finished:
                    floaters.remove(floater)

        if random.random() < 0.15:
            # Launch a new floater
            string = random.randrange(6)
            color = random.choice(Floater.COLORS)
            length = random.randint(4, 12)
            rate = random.random() * 0.4 + 0.4
            f = Floater(string, color, length, rate)
            self.floaters[string].add(f)
            bx[string] = True

        for n, b in enumerate(bx):
            if b:
                base = self.bases[n]
                base.copy_waves()
                for f in self.floaters[n]:
                    base.add_floater(f)
                base.update()

class BigCane:
    def __init__(self, first_n: int, second_n: int=-1) -> None:
        second_n = second_n if second_n > 0 else first_n + 1
        ip = LOOPBACK if simulation else PIXEL_CONTROLLER1
        self.u0 = RGBUniverse(DEFAULT_CID_BYTES, first_n, ip, 60)
        self.u1 = RGBUniverse(DEFAULT_CID_BYTES, second_n, ip, 60)
        segment = ['red'] * 6 + ['white'] * 9
        self.pixels = segment * 8
        self._update_universes()

    def initialize(self, mv: Multiverse) -> None:
        mv.add_universe(self.u0)
        mv.add_universe(self.u1)

    def _update_universes(self) -> None:
        self.u0.set_pixel_data(self.pixels[:60])
        self.u1.set_pixel_data(self.pixels[60:])

    def step(self) -> None:
        self.pixels = self.pixels[-1:] + self.pixels[:-1]
        self._update_universes()

class LittleCane:
    def __init__(self, n: int) -> None:
        ip = LOOPBACK if simulation else PIXEL_CONTROLLER2
        self.u = RGBUniverse(DEFAULT_CID_BYTES, n, ip, 60)
        segment = ['red'] * 6 + ['white'] * 9
        self.pixels = segment * 4
        self._update_universe()

    def _update_universe(self) -> None:
        self.u.set_pixel_data(self.pixels)

    def step(self) -> None:
        self.pixels = self.pixels[-1:] + self.pixels[:-1]
        self._update_universe()

    def initialize(self, mv: Multiverse) -> None:
        mv.add_universe(self.u)

class EveLight:
    def __init__(self, n: int) -> None:
        ip = LOOPBACK if simulation else PIXEL_CONTROLLER2
        self.u = RGBUniverse(DEFAULT_CID_BYTES, n, ip, 100)
        self.u.set_pixel_data(['white'] * 100)

    def initialize(self, mv: Multiverse) -> None:
        mv.add_universe(self.u)

def main() -> None:
    river = River()
    canes: list[BigCane|LittleCane] = []
    canes.extend([BigCane(n) for n in range(1, 9, 2)])
    canes.extend([LittleCane(n) for n in (25, 26, 27, 28)])
    eves = [EveLight(n) for n in (29, 30)]
    ticks = 0

    def cb(t: float) -> None:   # callback 50 times per second
        nonlocal ticks
        river.step(t)
        ticks += 1
        if ticks > 4:
            ticks = 0
            for c in canes:
                c.step()
        tdelta = time.time() - t
        if tdelta > 0.01:
            logger.debug("Time %s", tdelta)

    with Multiverse(fps=50, callback=cb) as mv:
        river.initialize(mv)
        for c in canes:
            c.initialize(mv)
        for ev in eves:
            ev.initialize(mv)
        mv.wait_for_kb()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        simulation = True
    try:
        main()
    except KeyboardInterrupt:
        pass
