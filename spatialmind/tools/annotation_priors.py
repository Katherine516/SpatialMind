"""Optional training-prior correction; never estimates priors from a query/test set."""

from collections import Counter


def reweight_votes(probabilities, classes, training_labels, power=0.0):
    import numpy as np

    power = float(power)
    if not np.isfinite(power) or not 0 <= power <= 1:
        raise ValueError("class_prior_power must be finite and between zero and one")
    counts = Counter(training_labels)
    frequencies = np.asarray([counts[label] for label in classes], dtype=float)
    values = np.asarray(probabilities, dtype=float)
    if np.any(frequencies <= 0) or values.ndim != 2 or values.shape[1] != len(classes):
        raise ValueError("Every probability column must have a positive training class count")
    if not np.isfinite(values).all() or np.any(values < 0) or np.any(values.sum(axis=1) <= 0):
        raise ValueError("Invalid neighbor probabilities")
    if power == 0:
        return values
    weighted = values / (frequencies / frequencies.sum()) ** power
    return weighted / weighted.sum(axis=1, keepdims=True)
