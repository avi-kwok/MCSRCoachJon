"""The idle rule: turn per-sample flags into idle stretches."""

from dataclasses import dataclass

from . import config


@dataclass
class Sample:
    time: float      # seconds into the video
    motion: float    # % of unmasked pixels that changed
    screen: str      # world / resized / inventory / pause / settings / f3
    still: bool = False
    dimension: str = ""   # overworld / nether / end / "" (unknown), see dimension.py
    reset: bool = False   # MCSR "reset this world?" dialog visible
    dim_src: str = ""     # where `dimension` came from: "f3" (debug text) / "colour" / ""
    loading: bool = False  # vanilla dirt-background loading screen (portal transition), see transition.py
    brick: float = 0.0    # share of nether-brick floor in front of the feet (fortress.py; world/f3 only)
    brick_up: float = 0.0  # ... and in the upper middle of the view (a brick wall, not a floor)
    portal: float = 0.0   # share of the game view under the purple nether-portal overlay


@dataclass
class Stretch:
    start: float
    end: float

    @property
    def duration(self):
        return self.end - self.start


def is_still(motion, screen):
    """Still = (almost) nothing moved AND the screen is one where that means idling."""
    return motion < config.MOTION_THRESHOLD and screen in config.IDLE_ELIGIBLE_SCREENS


def find_idle_stretches(samples, sample_interval):
    """Group consecutive still samples; keep groups lasting >= MIN_IDLE_SECONDS.

    Each sample stands for `sample_interval` seconds of video, so a run from
    sample a to sample b covers [a.time, b.time + interval).
    """
    stretches = []
    run_start = None
    for i, sample in enumerate(samples):
        if sample.still and run_start is None:
            run_start = i
        is_last = i == len(samples) - 1
        if run_start is not None and (not sample.still or is_last):
            run_end = i if (sample.still and is_last) else i - 1
            stretch = Stretch(samples[run_start].time, samples[run_end].time + sample_interval)
            if stretch.duration >= config.MIN_IDLE_SECONDS - 1e-6:
                stretches.append(stretch)
            run_start = None
    return stretches
