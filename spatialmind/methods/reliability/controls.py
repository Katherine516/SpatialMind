"""Ground-truth label sets for calibrating claim reliability.

`S_statistical` carries the caveat "heuristic until calibrated against
ground-truth positive/negative controls". Getting those controls does not need a
domain expert, because the truth is a property of how the data was built:

  * **negative** — permute cell labels among cells. Marginal composition is
    preserved and every label/position association is destroyed, so no cell-type
    pair is genuinely adjacent. Any co-localization claim from this run is false
    by construction.
  * **positive** — assign two labels by spatial position so the pair really is
    interleaved. The adjacency is true by construction.

What this can and cannot calibrate is worth being exact about. It calibrates
whether the score separates real spatial structure from a permutation null. It
does **not** calibrate whether a biological claim is true; that still needs a
reviewed claim-truth table, and the review packet stays the route to it.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
import math
import random


@dataclass
class ControlVariant:
    """One synthetic labelling with a known answer."""

    name: str
    arm: str                      # "positive" or "negative"
    truth_label: int
    labels: Dict[str, str]
    seed: int
    label_coverage: float
    implanted_pair: Tuple[str, str] = ("", "")
    notes: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)


def _thin(labels: Dict[str, str], coverage: float, rng: random.Random) -> Dict[str, str]:
    """Drop labels at random to move annotation coverage.

    Without this every variant has identical coverage, `A_annotation` is
    constant, and a fit cannot distinguish its contribution from the intercept.
    """
    if coverage >= 1.0:
        return dict(labels)
    keys = sorted(labels)
    rng.shuffle(keys)
    keep = keys[: max(1, int(round(len(keys) * coverage)))]
    return {key: labels[key] for key in keep}


def permuted_variant(
    cell_ids: Sequence[str],
    labels: Sequence[str],
    seed: int,
    coverage: float = 1.0,
) -> ControlVariant:
    """Negative control: same labels, shuffled between cells."""
    rng = random.Random(seed)
    shuffled = list(labels)
    rng.shuffle(shuffled)
    table = {cell_id: label for cell_id, label in zip(cell_ids, shuffled) if label}
    table = _thin(table, coverage, rng)
    return ControlVariant(
        name="permuted_s%d_c%02d" % (seed, round(coverage * 100)),
        arm="negative",
        truth_label=0,
        labels=table,
        seed=seed,
        label_coverage=coverage,
        notes="Labels permuted among cells; composition preserved, association destroyed.",
        meta={"construction": "label_permutation"},
    )


def implanted_variant(
    cell_ids: Sequence[str],
    xs: Sequence[float],
    ys: Sequence[float],
    seed: int,
    coverage: float = 1.0,
    pair: Tuple[str, str] = ("astrocyte", "oligodendrocyte"),
    stripe_microns: float = 60.0,
) -> ControlVariant:
    """Positive control: two labels interleaved in narrow stripes.

    Stripes rather than blocks, because a block puts most of each type's cells
    in its own interior where the other type is not a neighbour. Stripes narrow
    enough that a cell's k nearest neighbours cross the boundary make the
    adjacency real for most cells, which is the structure the enrichment test
    is supposed to find.

    `pair` must be cell-type names the section really uses. Naming the arms
    something synthetic would leak the answer: `P_panel` resolves labels to
    lineages and falls back to a constant for names it cannot resolve, so the
    positive arm would carry a different panel score and the fit would learn the
    arm from the label vocabulary instead of from the evidence.
    """
    rng = random.Random(seed)
    offset = rng.random() * stripe_microns
    first, second = pair
    table: Dict[str, str] = {}
    for cell_id, x, y in zip(cell_ids, xs, ys):
        band = int(math.floor((x + y + offset) / stripe_microns))
        table[cell_id] = first if band % 2 == 0 else second
    table = _thin(table, coverage, rng)
    return ControlVariant(
        name="implanted_s%d_c%02d" % (seed, round(coverage * 100)),
        arm="positive",
        truth_label=1,
        labels=table,
        seed=seed,
        label_coverage=coverage,
        implanted_pair=pair,
        notes="Two labels interleaved in %.0f um diagonal stripes; the pair is adjacent by construction."
              % stripe_microns,
        meta={"construction": "spatial_stripe_implant", "stripe_microns": stripe_microns},
    )


def build_control_grid(
    cell_ids: Sequence[str],
    xs: Sequence[float],
    ys: Sequence[float],
    labels: Sequence[str],
    seeds: Sequence[int] = (11, 23, 37),
    coverages: Sequence[float] = (1.0, 0.85, 0.72),
    stripe_microns: float = 60.0,
    pair: Optional[Tuple[str, str]] = None,
) -> List[ControlVariant]:
    """A balanced grid whose two arms differ only in spatial arrangement.

    The negative arm permutes *the positive arm's own labels*, not the section's
    original ones. Matching the label vocabulary is not tidiness, it is the whole
    validity of the comparison: `S_statistical` takes an unadjusted maximum over
    cell-type pairs, so an arm with ten labels draws its maximum from 55 pairs
    while a two-label arm draws from 3. The first measured grid did exactly that
    and scored the permutation null *above* the implanted truth -- a difference
    in multiple comparisons, not in evidence.

    Matched here: label vocabulary, marginal composition, coverage, cell count,
    pair count. Different: whether the two labels are spatially interleaved.
    """
    implant_pair = pair or ("astrocyte", "oligodendrocyte")
    variants: List[ControlVariant] = []
    for seed in seeds:
        for coverage in coverages:
            positive = implanted_variant(cell_ids, xs, ys, seed, coverage,
                                         pair=implant_pair, stripe_microns=stripe_microns)
            variants.append(positive)

            # Permute the positive arm's labels so both arms carry the same two
            # names in the same proportion, and only the arrangement differs.
            rng = random.Random(seed + 9001)
            keys = list(positive.labels)
            values = [positive.labels[key] for key in keys]
            rng.shuffle(values)
            negative = ControlVariant(
                name="permuted_s%d_c%02d" % (seed, round(coverage * 100)),
                arm="negative",
                truth_label=0,
                labels={key: value for key, value in zip(keys, values)},
                seed=seed,
                label_coverage=coverage,
                implanted_pair=implant_pair,
                notes="The positive arm's labels permuted among the same cells; "
                      "vocabulary, composition, coverage and pair count all matched.",
                meta={"construction": "matched_label_permutation"},
            )
            variants.append(negative)
    return variants


def summarize_grid(variants: Sequence[ControlVariant]) -> Dict[str, Any]:
    return {
        "variants": len(variants),
        "positive": sum(1 for v in variants if v.truth_label == 1),
        "negative": sum(1 for v in variants if v.truth_label == 0),
        "seeds": sorted({v.seed for v in variants}),
        "coverages": sorted({v.label_coverage for v in variants}),
    }
