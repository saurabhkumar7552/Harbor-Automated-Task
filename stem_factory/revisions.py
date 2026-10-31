from .errors import FactoryError


def revise_or_reject(candidate, feedback, limit):
    """Return failures to authoring until the configured revision limit is reached."""
    candidate['feedback'] = feedback
    if candidate['revision'] >= limit:
        candidate.update(status='rejected', revision_limit_reached=True,
                         reason='Repair limit reached; failed artifacts preserved')
    else:
        candidate['revision'] += 1
        candidate['status'] = 'author'
        candidate.pop('implementation', None)
        candidate.pop('audit', None)
        candidate.pop('final_findings', None)
        candidate.pop('stage', None)
    return candidate
