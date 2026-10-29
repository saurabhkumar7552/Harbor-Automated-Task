from .errors import FactoryError


def revise_or_reject(candidate, feedback, limit):
    """All failures return through authoring and an entirely new difficulty review."""
    candidate['feedback'] = feedback
    if candidate['revision'] >= limit:
        candidate.update(status='rejected', reason='Revision limit reached; failed artifacts preserved')
    else:
        candidate['revision'] += 1
        candidate['status'] = 'author'
        candidate.pop('implementation', None)
        candidate.pop('stage', None)
    return candidate
